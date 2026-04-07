from __future__ import annotations

import json
import os
from typing import Literal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from autopub.exceptions import AutopubException
from autopub.plugins import AutopubPlugin
from autopub.types import ReleaseInfo


class TypefullyConfig(BaseModel):
    social_set_id: str = Field(
        default_factory=lambda: os.environ.get("TYPEFULLY_SOCIAL_SET_ID", ""),
        validation_alias="social-set-id",
    )
    platforms: list[Literal["x", "linkedin", "threads", "bluesky", "mastodon"]] = Field(
        default_factory=lambda: ["x"],
    )
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
    max_length: int = Field(default=280, validation_alias="max-length")
    truncation_suffix: str = Field(default="...", validation_alias="truncation-suffix")
    dry_run: bool = Field(default=False, validation_alias="dry-run")


def _autopub_error(message: str) -> AutopubException:
    """Create an AutopubException with .message set for CLI compatibility."""
    exc = AutopubException(message)
    exc.message = message  # type: ignore[attr-defined]
    return exc


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
    ) -> str:
        variables = {
            "version": release_info.version or "",
            "release_type": release_info.release_type,
            "release_notes": release_info.release_notes,
            "previous_version": release_info.previous_version or "",
            "project_name": self.config.project_name,
        }

        message = template.format_map(variables)

        max_length = self.config.max_length
        if len(message) > max_length:
            suffix = self.config.truncation_suffix
            message = message[: max_length - len(suffix)] + suffix

        return message

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

    def _build_platforms_payload(
        self,
        release_info: ReleaseInfo,
    ) -> dict[str, object]:
        platforms: dict[str, object] = {}
        frontmatter_template = self._frontmatter_message_template(release_info)

        for platform in self.config.platforms:
            template = frontmatter_template or self.config.platform_templates.get(
                platform, self.config.message_template
            )
            message = self._format_message(template, release_info)
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
