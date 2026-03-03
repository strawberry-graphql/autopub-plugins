from __future__ import annotations

import os
from functools import cached_property
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from autopub.exceptions import AutopubException
from autopub.plugins import AutopubPlugin
from autopub.types import ReleaseInfo


class TypefullyConfig(BaseModel):
    social_set_id: str = Field(validation_alias="social-set-id")
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


class TypefullyPlugin(AutopubPlugin):
    """Announce releases on social media via Typefully."""

    id = "typefully"
    Config = TypefullyConfig

    def __init__(self) -> None:
        self.api_key = os.environ.get("TYPEFULLY_API_KEY")

        if not self.api_key:
            raise AutopubException("TYPEFULLY_API_KEY environment variable is required")

    BASE_URL = "https://api.typefully.com"

    @cached_property
    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

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

    def _build_platforms_payload(
        self,
        release_info: ReleaseInfo,
    ) -> list[dict[str, object]]:
        platforms = []

        for platform in self.config.platforms:
            template = self.config.platform_templates.get(
                platform,
                self.config.message_template,
            )
            message = self._format_message(template, release_info)
            platforms.append({"platform": platform, "text": message})

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
                raise AutopubException(
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

        response = self._client.post(url, json=body)

        if response.status_code == 401:
            raise AutopubException(
                "Typefully authentication failed: invalid API key"
            )

        if response.status_code == 429:
            raise AutopubException("Typefully rate limit exceeded, try again later")

        if not response.is_success:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise AutopubException(
                f"Typefully API error ({response.status_code}): {detail}"
            )

    def post_publish(self, release_info: ReleaseInfo) -> None:
        body = self._build_request_body(release_info)

        if self.config.dry_run:
            print(f"[typefully] dry run — request body: {body}")
            return

        self._create_draft(body)


__all__ = ["TypefullyPlugin"]
