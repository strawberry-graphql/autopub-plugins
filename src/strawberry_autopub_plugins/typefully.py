from __future__ import annotations

import json
import os
import re
from typing import Literal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator

from autopub.exceptions import AutopubException
from autopub.plugins import AutopubPlugin
from autopub.types import ReleaseInfo

Platform = Literal["x", "linkedin", "threads", "bluesky", "mastodon"]

SUPPORTED_PLATFORMS: tuple[str, ...] = (
    "x",
    "linkedin",
    "threads",
    "bluesky",
    "mastodon",
)

DEFAULT_MAX_LENGTHS: dict[str, int] = {
    "x": 280,
    "linkedin": 3000,
    "threads": 500,
    "bluesky": 300,
    "mastodon": 500,
}

MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
AUTOLINK_RE = re.compile(r"<(https?://[^>]+)>")
CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _unsupported_platform_message(source: str, platform: str) -> str:
    supported = ", ".join(SUPPORTED_PLATFORMS)
    return (
        f"{source} contains unsupported Typefully platform {platform!r}. "
        f"Supported platforms: {supported}"
    )


class TypefullyConfig(BaseModel):
    social_set_id: str = Field(
        default_factory=lambda: os.environ.get("TYPEFULLY_SOCIAL_SET_ID", ""),
        validation_alias="social-set-id",
    )
    platforms: list[Platform] = Field(default_factory=lambda: ["x"])
    message_template: str = Field(
        default="{project_name} {version} has been released!\n\n{release_notes}",
        validation_alias="message-template",
    )
    platform_templates: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="platform-templates",
    )
    project_name: str = Field(default="", validation_alias="project-name")
    publish_mode: Literal["draft", "now", "next-free-slot", "scheduled"] = Field(
        default="draft",
        validation_alias="publish-mode",
    )
    publish_at: str | None = Field(default=None, validation_alias="publish-at")
    tags: list[str] = Field(default_factory=list)
    require_social_message: bool = Field(
        default=False,
        validation_alias="require-social-message",
    )
    required_social_platforms: list[Platform] | None = Field(
        default=None,
        validation_alias="required-social-platforms",
    )
    require_release_note_lead: bool = Field(
        default=False,
        validation_alias="require-release-note-lead",
    )
    release_note_leads: list[str] = Field(
        default_factory=lambda: ["This release adds ", "This release fixes "],
        validation_alias="release-note-leads",
    )
    max_length: int | None = Field(default=None, validation_alias="max-length")
    platform_max_lengths: dict[str, int] = Field(
        default_factory=dict,
        validation_alias="platform-max-lengths",
    )
    truncation_suffix: str = Field(default="...", validation_alias="truncation-suffix")
    dry_run: bool = Field(default=False, validation_alias="dry-run")

    @field_validator("platform_max_lengths")
    @classmethod
    def _validate_platform_max_lengths(
        cls, platform_max_lengths: dict[str, int]
    ) -> dict[str, int]:
        for platform in platform_max_lengths:
            if platform not in SUPPORTED_PLATFORMS:
                raise ValueError(
                    _unsupported_platform_message("platform-max-lengths", platform)
                )

        return platform_max_lengths


def _autopub_error(message: str) -> AutopubException:
    """Create an AutopubException with .message set for CLI compatibility."""
    exc = AutopubException(message)
    exc.message = message  # type: ignore[attr-defined]
    return exc


def _validate_supported_platform(platform: str, *, source: str) -> None:
    if platform not in SUPPORTED_PLATFORMS:
        raise _autopub_error(_unsupported_platform_message(source, platform))


def _release_notes_markdown(release_info: ReleaseInfo) -> str:
    release_notes = release_info.release_notes

    if release_notes is None:
        return ""

    if not isinstance(release_notes, str):
        raise _autopub_error("Release notes must be a string")

    return release_notes.strip()


def _format_markdown_link(match: re.Match[str]) -> str:
    label = match.group(1).strip()
    url = match.group(2).strip()

    if label == url:
        return url

    return f"{label} ({url})"


def _markdown_to_social_text(markdown: str) -> str:
    text = markdown.strip()
    text = CODE_BLOCK_RE.sub(lambda match: match.group(1).strip(), text)
    text = MARKDOWN_LINK_RE.sub(_format_markdown_link, text)
    text = AUTOLINK_RE.sub(r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "- ", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "- ", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


class TypefullyPlugin(AutopubPlugin):
    """Announce releases on social media via Typefully."""

    id = "typefully"
    Config = TypefullyConfig
    BASE_URL = "https://api.typefully.com"

    @property
    def api_key(self) -> str:
        api_key = os.environ.get("TYPEFULLY_API_KEY")
        if not api_key:
            raise _autopub_error("TYPEFULLY_API_KEY environment variable is required")
        return api_key

    def _format_message(
        self,
        template: str,
        release_info: ReleaseInfo,
        platform: str,
    ) -> str:
        release_notes_markdown = _release_notes_markdown(release_info)
        release_notes = _markdown_to_social_text(release_notes_markdown)
        variables = {
            "version": release_info.version or "",
            "release_type": release_info.release_type,
            "release_notes": release_notes,
            "release_notes_markdown": release_notes_markdown,
            "release_notes_plain": release_notes,
            "previous_version": release_info.previous_version or "",
            "project_name": self.config.project_name,
        }

        message = template.format_map(variables)

        return self._truncate_message(message, platform)

    def _truncate_message(self, message: str, platform: str) -> str:
        max_length = self._max_length_for_platform(platform)

        if len(message) <= max_length:
            return message

        suffix = self.config.truncation_suffix

        if max_length <= len(suffix):
            return suffix[:max_length]

        limit = max_length - len(suffix)
        truncated = message[:limit].rstrip()
        boundary = max(truncated.rfind(" "), truncated.rfind("\n"))

        if boundary >= limit // 2:
            truncated = truncated[:boundary].rstrip()

        return f"{truncated}{suffix}"

    def _max_length_for_platform(self, platform: str) -> int:
        max_length = self.config.platform_max_lengths.get(platform)

        if max_length is None:
            max_length = self.config.max_length

        if max_length is None:
            max_length = DEFAULT_MAX_LENGTHS[platform]

        if max_length <= 0:
            raise _autopub_error(
                f"Maximum length for Typefully platform {platform!r} must be positive"
            )

        return max_length

    def _frontmatter_message_template(self, release_info: ReleaseInfo) -> str | None:
        additional_info = release_info.additional_info
        template = additional_info.get("social_message")

        if template is None:
            template = additional_info.get("social-message")

        if template is None:
            return None

        if not isinstance(template, str):
            raise _autopub_error("social_message frontmatter value must be a string")

        if not template.strip():
            raise _autopub_error("social_message frontmatter value cannot be empty")

        return template

    def _frontmatter_platform_message_templates(
        self, release_info: ReleaseInfo
    ) -> dict[str, str]:
        additional_info = release_info.additional_info
        templates = additional_info.get("social_messages")

        if templates is None:
            templates = additional_info.get("social-messages")

        if templates is None:
            return {}

        if not isinstance(templates, dict):
            raise _autopub_error("social_messages frontmatter value must be a mapping")

        platform_templates: dict[str, str] = {}

        for platform, template in templates.items():
            if not isinstance(platform, str):
                raise _autopub_error(
                    "social_messages frontmatter platform names must be strings"
                )

            _validate_supported_platform(
                platform, source="social_messages frontmatter"
            )

            if not isinstance(template, str):
                raise _autopub_error(
                    f"social_messages frontmatter value for {platform!r} "
                    "must be a string"
                )

            if not template.strip():
                raise _autopub_error(
                    f"social_messages frontmatter value for {platform!r} "
                    "cannot be empty"
                )

            platform_templates[platform] = template

        return platform_templates

    def _build_platforms_payload(
        self,
        release_info: ReleaseInfo,
    ) -> dict[str, object]:
        platforms: dict[str, object] = {}
        frontmatter_template = self._frontmatter_message_template(release_info)
        frontmatter_platform_templates = self._frontmatter_platform_message_templates(
            release_info
        )

        for platform in self.config.platforms:
            template = (
                frontmatter_platform_templates.get(platform)
                or frontmatter_template
                or self.config.platform_templates.get(
                    platform, self.config.message_template
                )
            )
            message = self._format_message(template, release_info, platform)
            platforms[platform] = {
                "enabled": True,
                "posts": [{"text": message}],
            }

        return platforms

    def _resolve_publish_at(self) -> str | None:
        mode = self.config.publish_mode

        if mode == "draft":
            return None

        if mode == "now":
            return "now"

        if mode == "next-free-slot":
            return "next-free-slot"

        if mode == "scheduled":
            if not self.config.publish_at:
                raise _autopub_error(
                    "publish-at is required when publish-mode is 'scheduled'"
                )
            return self.config.publish_at

        return None  # pragma: no cover

    def _build_request_body(
        self,
        release_info: ReleaseInfo,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "platforms": self._build_platforms_payload(release_info),
        }

        publish_at = self._resolve_publish_at()
        if publish_at is not None:
            body["publish_at"] = publish_at

        if self.config.tags:
            body["tags"] = self.config.tags

        return body

    def _validate_required_social_messages(self, release_info: ReleaseInfo) -> None:
        if not self.config.require_social_message:
            return

        frontmatter_template = self._frontmatter_message_template(release_info)

        if frontmatter_template is not None:
            return

        frontmatter_platform_templates = self._frontmatter_platform_message_templates(
            release_info
        )
        required_platforms = self.config.required_social_platforms

        if required_platforms is None:
            required_platforms = self.config.platforms

        missing_platforms = [
            platform
            for platform in required_platforms
            if platform not in frontmatter_platform_templates
        ]

        if missing_platforms:
            platforms = ", ".join(missing_platforms)
            raise _autopub_error(
                "Typefully social_messages frontmatter is required for: "
                f"{platforms}"
            )

    def _validate_release_note_lead(self, release_info: ReleaseInfo) -> None:
        if not self.config.require_release_note_lead:
            return

        release_notes = _release_notes_markdown(release_info).lstrip()

        if not release_notes:
            raise _autopub_error(
                "Release notes are required when require-release-note-lead is enabled"
            )

        if not release_notes.startswith(tuple(self.config.release_note_leads)):
            leads = ", ".join(
                repr(lead.strip()) for lead in self.config.release_note_leads
            )
            raise _autopub_error(
                "Release notes must start with an approved user-facing lead: "
                f"{leads}"
            )

    def validate_release_notes(self, release_info: ReleaseInfo) -> None:
        self._validate_required_social_messages(release_info)
        self._validate_release_note_lead(release_info)

    def _create_draft(self, body: dict[str, object]) -> None:
        social_set_id = self.config.social_set_id
        url = f"{self.BASE_URL}/v2/social-sets/{social_set_id}/drafts"

        data = json.dumps(body).encode()
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            urlopen(request)  # noqa: S310
        except HTTPError as exc:
            if exc.code == 401:
                raise _autopub_error(
                    "Typefully authentication failed: invalid API key"
                ) from exc

            if exc.code == 429:
                raise _autopub_error(
                    "Typefully rate limit exceeded, try again later"
                ) from exc

            try:
                error_body = json.loads(exc.read())
                detail = error_body.get("detail", str(exc))
            except Exception:
                detail = str(exc)

            raise _autopub_error(
                f"Typefully API error ({exc.code}): {detail}"
            ) from exc

    def post_publish(self, release_info: ReleaseInfo) -> None:
        body = self._build_request_body(release_info)

        if self.config.dry_run:
            print(f"[typefully] dry run — request body: {body}")
            return

        if not self.config.social_set_id:
            raise _autopub_error(
                "social-set-id config or TYPEFULLY_SOCIAL_SET_ID environment variable is required"
            )

        self._create_draft(body)


__all__ = ["TypefullyPlugin"]
