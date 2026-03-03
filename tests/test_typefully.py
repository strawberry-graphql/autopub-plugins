from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from autopub.exceptions import AutopubException
from autopub.types import ReleaseInfo
from strawberry_autopub_plugins.typefully import TypefullyPlugin


def _release_info(
    *,
    version: str | None = "1.0.0",
    previous_version: str | None = "0.9.0",
) -> ReleaseInfo:
    return ReleaseInfo(
        release_type="patch",
        release_notes="Bug fixes and improvements",
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


def _mock_client(*, status_code: int = 200, json_body: dict | None = None) -> MagicMock:
    mock = MagicMock(spec=httpx.Client)
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.is_success = 200 <= status_code < 300
    response.text = ""
    if json_body is not None:
        response.json.return_value = json_body
    else:
        response.json.return_value = {}
    mock.post.return_value = response
    return mock


def test_missing_api_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("TYPEFULLY_API_KEY", raising=False)

    with pytest.raises(AutopubException, match="TYPEFULLY_API_KEY"):
        TypefullyPlugin()


def test_creates_draft_default_config(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    mock.post.assert_called_once()
    url, kwargs = mock.post.call_args.args[0], mock.post.call_args.kwargs
    body = kwargs["json"]

    assert url == "/v2/social-sets/abc-123/drafts"
    assert len(body["platforms"]) == 1
    assert body["platforms"][0]["platform"] == "x"
    assert "1.0.0" in body["platforms"][0]["text"]
    assert "publish_at" not in body


def test_multiple_platforms(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"platforms": ["x", "linkedin", "bluesky"]},
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    platform_names = [p["platform"] for p in body["platforms"]]
    assert platform_names == ["x", "linkedin", "bluesky"]


def test_per_platform_templates(monkeypatch) -> None:
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
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    x_post = body["platforms"][0]
    linkedin_post = body["platforms"][1]

    assert x_post["text"] == "Short: 1.0.0"
    assert linkedin_post["text"] == "Long post about 1.0.0\n\nBug fixes and improvements"


def test_platform_template_fallback(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "platforms": ["x", "linkedin"],
            "platform-templates": {"x": "Custom X: {version}"},
            "project-name": "MyLib",
        },
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    x_post = body["platforms"][0]
    linkedin_post = body["platforms"][1]

    assert x_post["text"] == "Custom X: 1.0.0"
    assert linkedin_post["text"] == "MyLib 1.0.0 has been released!\n\nBug fixes and improvements"


def test_custom_message_template(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "message-template": "v{version} ({release_type}) is out!",
            "project-name": "Strawberry",
        },
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    assert body["platforms"][0]["text"] == "v1.0.0 (patch) is out!"


def test_message_truncation(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "message-template": "{release_notes}",
            "max-length": 20,
            "truncation-suffix": "…",
        },
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    text = body["platforms"][0]["text"]
    assert len(text) <= 20
    assert text.endswith("…")


def test_publish_mode_now(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"publish-mode": "now"},
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    assert body["publish_at"] == "now"


def test_publish_mode_next_free_slot(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"publish-mode": "next-free-slot"},
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    assert body["publish_at"] == "next-free-slot"


def test_publish_mode_scheduled(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={
            "publish-mode": "scheduled",
            "publish-at": "2026-01-15T10:00:00Z",
        },
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    assert body["publish_at"] == "2026-01-15T10:00:00Z"


def test_scheduled_without_publish_at_raises(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"publish-mode": "scheduled"},
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    with pytest.raises(AutopubException, match="publish-at is required"):
        plugin.post_publish(_release_info())


def test_tags_in_request(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"tags": ["release", "oss"]},
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    body = mock.post.call_args.kwargs["json"]
    assert body["tags"] == ["release", "oss"]


def test_dry_run_no_api_call(monkeypatch) -> None:
    plugin = _plugin_with_config(
        monkeypatch,
        config={"dry-run": True},
    )
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info())

    mock.post.assert_not_called()


def test_api_401_raises(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)
    mock = _mock_client(status_code=401)
    plugin.__dict__["_client"] = mock

    with pytest.raises(AutopubException, match="authentication failed"):
        plugin.post_publish(_release_info())


def test_api_429_raises(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)
    mock = _mock_client(status_code=429)
    plugin.__dict__["_client"] = mock

    with pytest.raises(AutopubException, match="rate limit"):
        plugin.post_publish(_release_info())


def test_api_generic_error(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)
    mock = _mock_client(status_code=500, json_body={"detail": "Internal server error"})
    plugin.__dict__["_client"] = mock

    with pytest.raises(AutopubException, match="Internal server error"):
        plugin.post_publish(_release_info())


def test_none_version_handled(monkeypatch) -> None:
    plugin = _plugin_with_config(monkeypatch)
    mock = _mock_client()
    plugin.__dict__["_client"] = mock

    plugin.post_publish(_release_info(version=None))

    body = mock.post.call_args.kwargs["json"]
    text = body["platforms"][0]["text"]
    assert "None" not in text
