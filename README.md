# strawberry-autopub-plugins

AutoPub plugins maintained by Strawberry GraphQL.

## Included plugins

- `InviteContributorsPlugin` (`strawberry_autopub_plugins.invite_contributors:InviteContributorsPlugin`)
  - Invites PR contributors to a GitHub organization after `autopub publish`.
  - Optionally adds them to a team.

## Installation

```bash
pip install strawberry-autopub-plugins
```

## Usage

Add the plugin path to your AutoPub config:

```toml
[tool.autopub]
plugins = [
  "poetry",
  "github",
  "strawberry_autopub_plugins.invite_contributors:InviteContributorsPlugin",
]

[tool.autopub.plugin_config.invite_contributors]
organization = "strawberry-graphql"
team-slug = "strawberry-contributors"
role = "direct_member"
skip-bots = true
include-co-authors = true
exclude-users = ["renovate[bot]"]
dry-run = false
```

## Required environment variables

- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`

The token must be able to invite users to the target organization.

## Development

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest
```

## Next plugin

This repository is structured to host multiple plugins under `src/strawberry_autopub_plugins/`.
