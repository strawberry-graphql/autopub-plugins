---
release type: minor
---

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
