---
release type: minor
---

This release adds `required-message-substrings` for Typefully release
announcements.

Projects can use this config to require platform-specific text in the rendered
social post, such as a release page URL for X:

```toml
[tool.autopub.plugin_config.typefully]
required-message-substrings = { x = ["https://example.com/releases/{version}"] }
```

Required substrings use the same template variables as messages and are checked
after truncation, so missing or truncated links fail before publishing.
