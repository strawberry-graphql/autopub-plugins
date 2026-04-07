from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from autopub.exceptions import AutopubException
from autopub.types import ReleaseInfo
from strawberry_autopub_plugins.typefully import TypefullyPlugin


def _release_info(
    *,
    version: str | None = "1.0.0",
    previous_version: str | None = "0.9.0",
    additional_info: dict | None = None,
) -> ReleaseInfo:
    return ReleaseInfo(
        release_type="patch",
        release_notes="Bug fixes and improvements",
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

    with pytest.raises(AutopubException, match="TYPEFULLY_API_KEY"):
        TypefullyPlugin()


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


def test_frontmatter_social_message_must_be_a_string(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)

    with pytest.raises(AutopubException, match="social_message frontmatter value must be a string"):
        plugin.post_publish(
            _release_info(
                additional_info={"social_message": ["not", "a", "string"]},
            )
        )


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
