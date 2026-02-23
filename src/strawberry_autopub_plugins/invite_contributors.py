from __future__ import annotations

import json
import os
from functools import cached_property
from typing import Literal

from github import Github
from github.GithubException import GithubException
from github.Organization import Organization
from github.PullRequest import PullRequest
from github.Repository import Repository
from github.Team import Team
from pydantic import BaseModel, Field

from autopub.exceptions import AutopubException
from autopub.plugins import AutopubPlugin
from autopub.types import ReleaseInfo


KNOWN_BOT_EXCLUSIONS = [
    "dependabot-preview[bot]",
    "dependabot-preview",
    "dependabot",
    "dependabot[bot]",
]


class InviteContributorsConfig(BaseModel):
    organization: str | None = None
    team_slug: str | None = Field(default=None, validation_alias="team-slug")
    role: Literal["direct_member", "admin", "billing_manager"] = "direct_member"
    skip_bots: bool = Field(default=True, validation_alias="skip-bots")
    include_co_authors: bool = Field(
        default=True,
        validation_alias="include-co-authors",
    )
    exclude_users: list[str] = Field(
        default_factory=lambda: list(KNOWN_BOT_EXCLUSIONS),
        validation_alias="exclude-users",
    )
    dry_run: bool = Field(default=False, validation_alias="dry-run")


class InviteContributorsPlugin(AutopubPlugin):
    """Invite PR contributors to a GitHub organization (and optional team)."""

    id = "invite_contributors"
    Config = InviteContributorsConfig

    def __init__(self) -> None:
        self.github_token = os.environ.get("GITHUB_TOKEN")
        self.repository_name = os.environ.get("GITHUB_REPOSITORY")

        if not self.github_token:
            raise AutopubException("GITHUB_TOKEN environment variable is required")

        if not self.repository_name:
            raise AutopubException("GITHUB_REPOSITORY environment variable is required")

    @cached_property
    def _github(self) -> Github:
        return Github(self.github_token)

    @cached_property
    def _event_data(self) -> dict | None:
        event_path = os.environ.get("GITHUB_EVENT_PATH")

        if not event_path:
            return None

        with open(event_path) as f:
            return json.load(f)

    @cached_property
    def repository(self) -> Repository:
        return self._github.get_repo(self.repository_name)

    @cached_property
    def pull_request(self) -> PullRequest | None:
        pr_number = self._get_pr_number()

        if pr_number is None:
            return None

        return self.repository.get_pull(pr_number)

    def _get_pr_number(self) -> int | None:
        if not self._event_data:
            return None

        if self._event_data.get("pull_request"):
            return self._event_data["pull_request"]["number"]

        if self._event_data.get("head_commit"):
            sha = self._event_data["head_commit"]["id"]
        else:
            commits = self._event_data.get("commits", [])
            if not commits:
                return None
            sha = commits[0]["id"]

        commit = self.repository.get_commit(sha)
        pulls = commit.get_pulls()

        try:
            return pulls[0].number
        except IndexError:
            return None

    def _get_pr_contributors(self, pr: PullRequest) -> set[str]:
        contributors: set[str] = {pr.user.login}

        for commit in pr.get_commits():
            author = getattr(commit, "author", None)
            if author and getattr(author, "login", None):
                contributors.add(author.login)

            if self.config.include_co_authors:
                for line in commit.commit.message.splitlines():
                    if not line.startswith("Co-authored-by:"):
                        continue

                    trailer_value = line.split(":", 1)[1].strip()
                    login = trailer_value.split(" ", 1)[0].lstrip("@")

                    if login:
                        contributors.add(login)

        return contributors

    def _filter_contributors(self, contributors: set[str]) -> list[str]:
        excluded_users = set(self.config.exclude_users)
        filtered = []

        for login in sorted(contributors):
            if login in excluded_users:
                continue

            if self.config.skip_bots and login.endswith("[bot]"):
                continue

            filtered.append(login)

        return filtered

    def _resolve_organization(self) -> Organization:
        if self.config.organization:
            return self._github.get_organization(self.config.organization)

        if self.repository.organization:
            return self._github.get_organization(self.repository.organization.login)

        raise AutopubException(
            "No organization configured. Set tool.autopub.plugin_config"
            ".invite_contributors.organization"
        )

    def _resolve_team(self, organization: Organization) -> Team | None:
        if not self.config.team_slug:
            return None

        return organization.get_team_by_slug(self.config.team_slug)

    def _invite_login(self, organization: Organization, team: Team | None, login: str) -> None:
        user = self._github.get_user(login)

        invite_kwargs: dict[str, object] = {
            "user": user,
            "role": self.config.role,
        }

        if team is not None:
            invite_kwargs["teams"] = [team]

        try:
            organization.invite_user(**invite_kwargs)
        except GithubException as exc:
            # 422 usually means already invited or already a member.
            if exc.status == 422:
                return

            message = str(exc)
            if isinstance(exc.data, dict):
                message = exc.data.get("message", message)

            raise AutopubException(f"Failed to invite @{login}: {message}") from exc

    def post_publish(self, release_info: ReleaseInfo) -> None:
        del release_info

        pr = self.pull_request
        if pr is None:
            return

        contributors = self._get_pr_contributors(pr)
        contributors_to_invite = self._filter_contributors(contributors)

        if not contributors_to_invite:
            return

        organization = self._resolve_organization()
        team = self._resolve_team(organization)

        for login in contributors_to_invite:
            if self.config.dry_run:
                print(f"[invite_contributors] would invite @{login}")
                continue

            self._invite_login(organization, team, login)


__all__ = ["InviteContributorsPlugin"]
