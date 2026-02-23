from __future__ import annotations

from unittest.mock import MagicMock

from github.GithubException import GithubException

from autopub.types import ReleaseInfo
from strawberry_autopub_plugins.invite_contributors import (
    KNOWN_BOT_EXCLUSIONS,
    InviteContributorsPlugin,
)


def _release_info() -> ReleaseInfo:
    return ReleaseInfo(
        release_type="patch",
        release_notes="Test release notes",
        version="1.0.0",
        previous_version="0.9.0",
    )


def _plugin_with_config(monkeypatch) -> InviteContributorsPlugin:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "strawberry-graphql/strawberry")

    plugin = InviteContributorsPlugin()
    plugin.validate_config(
        {
            "plugin_config": {
                "invite_contributors": {
                    "organization": "strawberry-graphql",
                    "team-slug": "strawberry-contributors",
                }
            }
        }
    )
    return plugin


def test_invites_pr_author_and_contributors(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    pull_request = MagicMock()
    pull_request.user.login = "author"

    author_commit = MagicMock()
    author_commit.author.login = "author"
    author_commit.commit.message = "Initial commit"

    contributor_commit = MagicMock()
    contributor_commit.author.login = "teammate"
    contributor_commit.commit.message = "Fixes\nCo-authored-by: @helper <helper@example.com>"

    bot_commit = MagicMock()
    bot_commit.author.login = "dependabot[bot]"
    bot_commit.commit.message = "Bump dependency"

    pull_request.get_commits.return_value = [author_commit, contributor_commit, bot_commit]

    plugin.pull_request = pull_request

    mock_github = MagicMock()
    mock_org = MagicMock()
    mock_team = MagicMock()

    mock_github.get_organization.return_value = mock_org
    mock_org.get_team_by_slug.return_value = mock_team

    plugin._github = mock_github

    plugin.post_publish(_release_info())

    invited_logins = [call.args[0] for call in mock_github.get_user.call_args_list]

    assert set(invited_logins) == {"author", "teammate", "helper"}
    assert "dependabot[bot]" not in invited_logins

    for call in mock_org.invite_user.call_args_list:
        assert call.kwargs["role"] == "direct_member"
        assert call.kwargs["teams"] == [mock_team]


def test_ignores_existing_members_and_invites(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    pull_request = MagicMock()
    pull_request.user.login = "author"

    commit = MagicMock()
    commit.author.login = "author"
    commit.commit.message = "Initial commit"
    pull_request.get_commits.return_value = [commit]

    plugin.pull_request = pull_request

    mock_github = MagicMock()
    mock_org = MagicMock()

    mock_github.get_organization.return_value = mock_org
    mock_org.get_team_by_slug.return_value = None
    mock_org.invite_user.side_effect = GithubException(
        422,
        {"message": "Invitee is already a part of this organization"},
    )

    plugin._github = mock_github

    plugin.post_publish(_release_info())

    assert mock_org.invite_user.call_count == 1


def test_skips_when_no_pull_request(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    plugin.pull_request = None

    mock_github = MagicMock()
    plugin._github = mock_github

    plugin.post_publish(_release_info())

    mock_github.get_organization.assert_not_called()


def test_default_config_skips_known_bot_usernames(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "strawberry-graphql/strawberry")

    plugin = InviteContributorsPlugin()
    plugin.validate_config({})

    filtered = plugin._filter_contributors(
        {
            "author",
            "dependabot",
            "dependabot-preview",
            "dependabot[bot]",
            "dependabot-preview[bot]",
        }
    )

    assert plugin.config.skip_bots is True
    assert plugin.config.exclude_users == KNOWN_BOT_EXCLUSIONS
    assert filtered == ["author"]
