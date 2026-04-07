# strawberry-autopub-plugins

AutoPub plugins maintained by Strawberry GraphQL.

## Included plugins

- `InviteContributorsPlugin` (`strawberry_autopub_plugins.invite_contributors:InviteContributorsPlugin`)
  - Invites pull request contributors to a GitHub organization after `autopub publish`.
  - Can also add invited users to a GitHub team.
- `TypefullyPlugin` (`strawberry_autopub_plugins.typefully:TypefullyPlugin`)
  - Creates Typefully drafts or scheduled posts for release announcements.
  - Supports per-platform templates for `x`, `linkedin`, `threads`, `bluesky`, and `mastodon`.

## Installation

```bash
pip install strawberry-autopub-plugins
```

## Usage

Add one or more plugin paths to your AutoPub config:

```toml
[tool.autopub]
plugins = [
  "poetry",
  "github",
  "strawberry_autopub_plugins.invite_contributors:InviteContributorsPlugin",
  "strawberry_autopub_plugins.typefully:TypefullyPlugin",
]
```

Plugin config is keyed by each plugin's `id`:

- `invite_contributors`
- `typefully`

## InviteContributorsPlugin

Plugin path:

```text
strawberry_autopub_plugins.invite_contributors:InviteContributorsPlugin
```

Required environment variables:

- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`

Optional environment variables:

- `GITHUB_EVENT_PATH`

`GITHUB_TOKEN` must be able to invite users to the target organization.

Example config:

```toml
[tool.autopub.plugin_config.invite_contributors]
organization = "strawberry-graphql"
team-slug = "strawberry-contributors"
role = "direct_member"
skip-bots = true
include-co-authors = true
exclude-users = ["renovate[bot]"]
dry-run = false
```

Options:

- `organization`: Target GitHub organization. If omitted, the plugin falls back to the repository organization.
- `team-slug`: Optional team slug to add invited contributors to.
- `role`: One of `direct_member`, `admin`, or `billing_manager`. Default: `direct_member`.
- `skip-bots`: Skip logins ending in `[bot]`. Default: `true`.
- `include-co-authors`: Include `Co-authored-by:` trailers found in commit messages. Default: `true`.
- `exclude-users`: Additional usernames to skip. Defaults to `dependabot-preview[bot]`, `dependabot-preview`, `dependabot`, and `dependabot[bot]`.
- `dry-run`: Print which users would be invited without sending invitations. Default: `false`.

## TypefullyPlugin

Plugin path:

```text
strawberry_autopub_plugins.typefully:TypefullyPlugin
```

Required environment variables:

- `TYPEFULLY_API_KEY`

Optional environment variables:

- `TYPEFULLY_SOCIAL_SET_ID`

You can provide the social set ID either through `social-set-id` in config or `TYPEFULLY_SOCIAL_SET_ID`.

Example config:

```toml
[tool.autopub.plugin_config.typefully]
social-set-id = "abc-123"
platforms = ["x", "linkedin", "bluesky"]
project-name = "Strawberry"
message-template = "{project_name} {version} has been released!\n\n{release_notes}"
publish-mode = "draft"
tags = ["release", "python"]
max-length = 280
truncation-suffix = "..."
dry-run = false

[tool.autopub.plugin_config.typefully.platform-templates]
x = "{project_name} {version} is out now.\n\n{release_notes}"
linkedin = "{project_name} {version} has been released.\n\n{release_notes}"
```

Options:

- `social-set-id`: Typefully social set to post into. Required unless `TYPEFULLY_SOCIAL_SET_ID` is set.
- `platforms`: Platforms to enable. Supported values: `x`, `linkedin`, `threads`, `bluesky`, `mastodon`. Default: `["x"]`.
- `message-template`: Default template for all platforms. Default: `{project_name} {version} has been released!\n\n{release_notes}`.
- `platform-templates`: Per-platform template overrides.
- `project-name`: Value exposed to templates as `{project_name}`.
- `publish-mode`: One of `draft`, `now`, `next-free-slot`, or `scheduled`. Default: `draft`.
- `publish-at`: Required when `publish-mode = "scheduled"`.
- `tags`: Optional Typefully tags to attach to the draft.
- `max-length`: Maximum post length before truncation. Default: `280`.
- `truncation-suffix`: Suffix appended after truncation. Default: `...`.
- `dry-run`: Print the request body without calling the Typefully API. Default: `false`.

Template variables:

- `{project_name}`
- `{version}`
- `{release_type}`
- `{release_notes}`
- `{previous_version}`

Release-specific override from `RELEASE.md` frontmatter:

```md
---
release type: patch
social_message: |
  Strawberry {version} is out now.

  Highlights:
  {release_notes}
---

- Fixed X
- Added Y
```

When `social_message` is present in AutoPub frontmatter, the plugin uses it as the message template for all configured platforms and still expands the same template variables listed above.

## Development

```bash
uv sync
uv run pytest
```

When changing dependencies, update the lockfile:

```bash
uv lock
```
