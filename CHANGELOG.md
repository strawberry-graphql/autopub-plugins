CHANGELOG
=========

0.3.0 - 2026-07-08
------------------

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

This release was contributed by [@patrick91](https://github.com/patrick91) in [#8](https://github.com/strawberry-graphql/autopub-plugins/pull/8)

0.2.0 - 2026-06-29
------------------

This release improves Typefully release announcements.

AutoPub now formats Markdown release notes as social-friendly plain text when
using the `{release_notes}` template variable, keeping raw Markdown available as
`{release_notes_markdown}` for callers that need it. This avoids posts showing
raw Markdown link syntax such as `[label](url)`.

Typefully messages now use platform-specific length defaults, so LinkedIn posts
are no longer truncated to X's 280-character limit. Projects can still set a
global `max-length`, or override individual platforms with
`platform-max-lengths`.

Release files can also define `social_messages` frontmatter for per-platform
announcements, with each platform override taking precedence over the shared
`social_message` template. Typefully now validates platform names used in
`platform-max-lengths` and `social_messages`, so typos fail early instead of
being ignored.

Projects that want release copy to be reviewed before publishing can now enable
`require-social-message`, `required-social-platforms`, and
`require-release-note-lead` to fail AutoPub checks when release notes are missing
social copy or do not start with the configured user-facing lead phrases.

This release was contributed by [@patrick91](https://github.com/patrick91) in [#7](https://github.com/strawberry-graphql/autopub-plugins/pull/7)

0.1.2 - 2026-04-07
------------------

Test patch release to validate the AutoPub GitHub Actions workflow.

This release was contributed by [@patrick91](https://github.com/patrick91) in [#6](https://github.com/strawberry-graphql/autopub-plugins/pull/6)