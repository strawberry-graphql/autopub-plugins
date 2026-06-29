from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from autopub.exceptions import AutopubException
from autopub.types import ReleaseInfo
from pydantic import ValidationError
from strawberry_autopub_plugins.typefully import TypefullyPlugin


def _release_info(
    *,
    version: str | None = "1.0.0",
    previous_version: str | None = "0.9.0",
    release_notes: str | None = "Bug fixes and improvements",
    additional_info: dict | None = None,
) -> ReleaseInfo:
    return ReleaseInfo(
        release_type="patch",
        release_notes=release_notes,
        additional_info=additional_info or {},
        version=version,
        previous_version=previous_version,
    )


def _plugin_with_config(
    monkeypatch,
    *,
    config: dict | None = None,
) -> TypefullyPlugin:
    monkeypatch.setenv("TYPEFULLY_API_KEY", "test-api-key")

    plugin = TypefullyPlugin()

    plugin_config = {"social-set-id": "abc-123"}
    if config:
        plugin_config.update(config)

    plugin.validate_config({"plugin_config": {"typefully": plugin_config}})
    return plugin


def _mock_urlopen(*, status_code: int = 200, body: dict | None = None):
    if status_code >= 400:
        error = HTTPError(
            url="https://api.typefully.com/v2/social-sets/abc-123/drafts",
            code=status_code,
            msg="Error",
            hdrs={},  # type: ignore[arg-type]
            fp=None,
        )
        if body is not None:
            error.read = MagicMock(return_value=json.dumps(body).encode())  # type: ignore[assignment]
        else:
            error.read = MagicMock(return_value=b"{}")  # type: ignore[assignment]
        return MagicMock(side_effect=error)

    mock_response = MagicMock()
    mock_response.status = status_code
    if body is not None:
        mock_response.read.return_value = json.dumps(body).encode()
    return MagicMock(return_value=mock_response)


def _get_request_body(mock_urlopen) -> dict:
    return json.loads(mock_urlopen.call_args.args[0].data)


def test_missing_api_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("TYPEFULLY_API_KEY", raising=False)

    plugin = TypefullyPlugin()
    plugin.validate_config({"plugin_config": {"typefully": {"social-set-id": "abc-123"}}})

    with pytest.raises(AutopubException, match="TYPEFULLY_API_KEY"):
        plugin.post_publish(_release_info())


def test_dry_run_does_not_require_api_key_or_social_set_id(monkeypatch, capsys) -> None:
    monkeypatch.delenv("TYPEFULLY_API_KEY", raising=False)
    monkeypatch.delenv("TYPEFULLY_SOCIAL_SET_ID", raising=False)

    plugin = TypefullyPlugin()
    plugin.validate_config({"plugin_config": {"typefully": {"dry-run": True}}})

    plugin.post_publish(_release_info())

    output = capsys.readouterr().out
    assert "[typefully] dry run" in output


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_creates_draft_default_config(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    plugin.post_publish(_release_info())

    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args.args[0]

    assert request.full_url == "https://api.typefully.com/v2/social-sets/abc-123/drafts"
    assert request.get_header("Authorization") == "Bearer test-api-key"

    body = _get_request_body(mock_urlopen)
    assert "x" in body["platforms"]
    assert body["platforms"]["x"]["enabled"] is True
    assert "1.0.0" in body["platforms"]["x"]["posts"][0]["text"]
    assert "publish_at" not in body


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_multiple_platforms(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"platforms": ["x", "linkedin", "bluesky"]},
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert set(body["platforms"].keys()) == {"x", "linkedin", "bluesky"}
    for platform in body["platforms"].values():
        assert platform["enabled"] is True


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_per_platform_templates(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "platform-templates": {
                "x": "Short: {version}",
                "linkedin": "Long post about {version}\n\n{release_notes}",
            },
        },
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert body["platforms"]["x"]["posts"][0]["text"] == "Short: 1.0.0"
    assert (
        body["platforms"]["linkedin"]["posts"][0]["text"]
        == "Long post about 1.0.0\n\nBug fixes and improvements"
    )


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_platform_template_fallback(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "platform-templates": {"x": "Custom X: {version}"},
            "project-name": "MyLib",
        },
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert body["platforms"]["x"]["posts"][0]["text"] == "Custom X: 1.0.0"
    assert (
        body["platforms"]["linkedin"]["posts"][0]["text"]
        == "MyLib 1.0.0 has been released!\n\nBug fixes and improvements"
    )


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_custom_message_template(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "message-template": "v{version} ({release_type}) is out!",
            "project-name": "Strawberry",
        },
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert body["platforms"]["x"]["posts"][0]["text"] == "v1.0.0 (patch) is out!"


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_frontmatter_social_message_overrides_templates(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "message-template": "Default {version}",
            "platform-templates": {"linkedin": "LinkedIn {version}"},
            "project-name": "Strawberry",
        },
    )

    plugin.post_publish(
        _release_info(
            additional_info={
                "social_message": "{project_name} {version} shipped\n\n{release_notes}"
            }
        )
    )

    body = _get_request_body(mock_urlopen)
    assert (
        body["platforms"]["x"]["posts"][0]["text"]
        == "Strawberry 1.0.0 shipped\n\nBug fixes and improvements"
    )
    assert (
        body["platforms"]["linkedin"]["posts"][0]["text"]
        == "Strawberry 1.0.0 shipped\n\nBug fixes and improvements"
    )


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_frontmatter_social_messages_override_individual_platforms(
    mock_urlopen, monkeypatch
) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "project-name": "Strawberry",
        },
    )

    plugin.post_publish(
        _release_info(
            additional_info={
                "social_message": "{project_name} {version} shipped",
                "social_messages": {
                    "linkedin": (
                        "{project_name} {version} shipped with more LinkedIn detail"
                    ),
                },
            }
        )
    )

    body = _get_request_body(mock_urlopen)
    assert body["platforms"]["x"]["posts"][0]["text"] == "Strawberry 1.0.0 shipped"
    assert (
        body["platforms"]["linkedin"]["posts"][0]["text"]
        == "Strawberry 1.0.0 shipped with more LinkedIn detail"
    )


def test_frontmatter_social_message_must_be_a_string(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    with pytest.raises(
        AutopubException,
        match="social_message frontmatter value must be a string",
    ):
        plugin.post_publish(
            _release_info(
                additional_info={"social_message": ["not", "a", "string"]},
            )
        )


def test_frontmatter_social_messages_must_be_a_mapping(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    with pytest.raises(
        AutopubException, match="social_messages frontmatter value must be a mapping"
    ):
        plugin.post_publish(
            _release_info(
                additional_info={"social_messages": ["not", "a", "mapping"]},
            )
        )


def test_frontmatter_social_messages_reject_unknown_platform(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    with pytest.raises(
        AutopubException,
        match="social_messages frontmatter contains unsupported Typefully platform "
        "'twitter'",
    ):
        plugin.post_publish(
            _release_info(
                additional_info={
                    "social_messages": {
                        "twitter": "Strawberry 1.0.0 is out",
                    },
                },
            )
        )


def test_required_social_message_accepts_shared_social_message(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "require-social-message": True,
        },
    )

    plugin.validate_release_notes(
        _release_info(
            additional_info={
                "social_message": "{project_name} {version} shipped",
            },
        )
    )


def test_required_social_message_requires_each_configured_platform(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "require-social-message": True,
        },
    )

    with pytest.raises(
        AutopubException,
        match="Typefully social_messages frontmatter is required for: linkedin",
    ):
        plugin.validate_release_notes(
            _release_info(
                additional_info={
                    "social_messages": {
                        "x": "Short release post",
                    },
                },
            )
        )


def test_required_social_platforms_allow_subset(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin", "mastodon"],
            "require-social-message": True,
            "required-social-platforms": ["x", "linkedin"],
        },
    )

    plugin.validate_release_notes(
        _release_info(
            additional_info={
                "social_messages": {
                    "x": "Short release post",
                    "linkedin": "Longer release post",
                },
            },
        )
    )


def test_release_note_lead_can_be_required(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"require-release-note-lead": True},
    )

    plugin.validate_release_notes(
        _release_info(release_notes="This release fixes schema output.")
    )


def test_release_note_lead_rejects_implementation_first_copy(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"require-release-note-lead": True},
    )

    with pytest.raises(
        AutopubException,
        match="Release notes must start with an approved user-facing lead",
    ):
        plugin.validate_release_notes(
            _release_info(release_notes="Refactor the internal schema printer.")
        )


@pytest.mark.parametrize("release_notes", [None, "", "   "])
def test_release_note_lead_requires_release_notes(monkeypatch, release_notes) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"require-release-note-lead": True},
    )

    with pytest.raises(
        AutopubException,
        match="Release notes are required when require-release-note-lead is enabled",
    ):
        plugin.validate_release_notes(_release_info(release_notes=release_notes))


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_message_truncation(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "message-template": "{release_notes}",
            "max-length": 20,
            "truncation-suffix": "…",
        },
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    text = body["platforms"]["x"]["posts"][0]["text"]
    assert len(text) <= 20
    assert text.endswith("…")


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_message_truncation_very_small_limit_uses_suffix_slice(
    mock_urlopen, monkeypatch
) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "message-template": "{release_notes}",
            "platform-max-lengths": {
                "x": 2,
            },
        },
    )

    plugin.post_publish(_release_info(release_notes="word " * 20))

    body = _get_request_body(mock_urlopen)
    text = body["platforms"]["x"]["posts"][0]["text"]
    assert text == ".."


@patch("strawberry_autopub_plugins.typefully.urlopen")
@pytest.mark.parametrize("invalid_length", [0, -1])
def test_platform_max_length_must_be_positive_on_publish(
    mock_urlopen, monkeypatch, invalid_length
) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "message-template": "{release_notes}",
            "platform-max-lengths": {
                "x": invalid_length,
            },
        },
    )

    with pytest.raises(
        AutopubException,
        match=r"Maximum length for Typefully platform 'x' must be positive",
    ):
        plugin.post_publish(_release_info(release_notes="word " * 20))

    mock_urlopen.assert_not_called()


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_message_truncation_respects_word_boundary(
    mock_urlopen, monkeypatch
) -> None:
    message = (
        "Strawberry is a GraphQL library for Python that makes it easy "
        "to build APIs."
    )
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "message-template": "{release_notes}",
            "max-length": 50,
        },
    )

    plugin.post_publish(_release_info(release_notes=message))

    body = _get_request_body(mock_urlopen)
    text = body["platforms"]["x"]["posts"][0]["text"]
    visible = text.removesuffix("...")

    assert len(text) <= 50
    assert text.endswith("...")
    assert message.startswith(visible)
    assert message[len(visible)] == " "


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_default_message_truncation_is_platform_specific(
    mock_urlopen, monkeypatch
) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "message-template": "{release_notes}",
        },
    )

    plugin.post_publish(_release_info(release_notes="word " * 100))

    body = _get_request_body(mock_urlopen)
    x_text = body["platforms"]["x"]["posts"][0]["text"]
    linkedin_text = body["platforms"]["linkedin"]["posts"][0]["text"]

    assert len(x_text) <= 280
    assert x_text.endswith("...")
    assert linkedin_text == ("word " * 100).strip()


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_platform_max_lengths_override_defaults(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "message-template": "{release_notes}",
            "platform-max-lengths": {
                "linkedin": 40,
            },
        },
    )

    plugin.post_publish(_release_info(release_notes="word " * 100))

    body = _get_request_body(mock_urlopen)
    x_text = body["platforms"]["x"]["posts"][0]["text"]
    linkedin_text = body["platforms"]["linkedin"]["posts"][0]["text"]

    assert len(x_text) <= 280
    assert len(linkedin_text) <= 40
    assert linkedin_text.endswith("...")


def test_platform_max_lengths_reject_unknown_platform(monkeypatch) -> None:
    with pytest.raises(
        ValidationError,
        match="platform-max-lengths contains unsupported Typefully platform 'twitter'",
    ):
        _plugin_with_config(
            monkeypatch,
            config={
                "platform-max-lengths": {
                    "twitter": 280,
                },
            },
        )


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_release_notes_variable_is_social_text(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"message-template": "{release_notes}"},
    )

    plugin.post_publish(
        _release_info(
            release_notes=(
                "See [GraphQL over SSE](https://example.com/protocol.md) and "
                "enable `GRAPHQL_SSE_PROTOCOL`."
            )
        )
    )

    body = _get_request_body(mock_urlopen)
    text = body["platforms"]["x"]["posts"][0]["text"]

    assert "[GraphQL over SSE]" not in text
    assert "`GRAPHQL_SSE_PROTOCOL`" not in text
    assert "GraphQL over SSE (https://example.com/protocol.md)" in text
    assert "GRAPHQL_SSE_PROTOCOL" in text


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_release_notes_markdown_variable_preserves_markdown(
    mock_urlopen, monkeypatch
) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"message-template": "{release_notes_markdown}"},
    )

    plugin.post_publish(
        _release_info(
            release_notes="See [GraphQL over SSE](https://example.com/protocol.md)."
        )
    )

    body = _get_request_body(mock_urlopen)
    text = body["platforms"]["x"]["posts"][0]["text"]

    assert text == "See [GraphQL over SSE](https://example.com/protocol.md)."


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_publish_mode_now(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"publish-mode": "now"},
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert body["publish_at"] == "now"


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_publish_mode_next_free_slot(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"publish-mode": "next-free-slot"},
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert body["publish_at"] == "next-free-slot"


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_publish_mode_scheduled(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "publish-mode": "scheduled",
            "publish-at": "2026-01-15T10:00:00Z",
        },
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert body["publish_at"] == "2026-01-15T10:00:00Z"


def test_scheduled_without_publish_at_raises(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"publish-mode": "scheduled"},
    )

    with pytest.raises(AutopubException, match="publish-at is required"):
        plugin.post_publish(_release_info())


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_tags_in_request(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"tags": ["release", "oss"]},
    )

    plugin.post_publish(_release_info())

    body = _get_request_body(mock_urlopen)
    assert body["tags"] == ["release", "oss"]


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_dry_run_no_api_call(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"dry-run": True},
    )

    plugin.post_publish(_release_info())

    mock_urlopen.assert_not_called()


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_api_401_raises(mock_urlopen, monkeypatch) -> None:
    mock_urlopen.side_effect = _mock_urlopen(status_code=401).side_effect
    plugin = _plugin_with_config(monkeypatch)

    with pytest.raises(AutopubException, match="authentication failed"):
        plugin.post_publish(_release_info())


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_api_429_raises(mock_urlopen, monkeypatch) -> None:
    mock_urlopen.side_effect = _mock_urlopen(status_code=429).side_effect
    plugin = _plugin_with_config(monkeypatch)

    with pytest.raises(AutopubException, match="rate limit"):
        plugin.post_publish(_release_info())


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_api_generic_error(mock_urlopen, monkeypatch) -> None:
    mock_urlopen.side_effect = _mock_urlopen(
        status_code=500, body={"detail": "Internal server error"}
    ).side_effect
    plugin = _plugin_with_config(monkeypatch)

    with pytest.raises(AutopubException, match="Internal server error"):
        plugin.post_publish(_release_info())


@patch("strawberry_autopub_plugins.typefully.urlopen")
def test_none_version_handled(mock_urlopen, monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    plugin.post_publish(_release_info(version=None))

    body = _get_request_body(mock_urlopen)
    text = body["platforms"]["x"]["posts"][0]["text"]
    assert "None" not in text
