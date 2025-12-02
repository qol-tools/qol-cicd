# qol-tools

Organization-wide configuration and workflows.

## Workflows

### Auto-label qol-tray plugins

Adds the `qol-tray-plugin` topic when a repo starting with `plugin-` is created.

### Release plugins

Automatically releases all plugins with the `qol-tray-plugin` topic using semantic-release.

- Scans all repos with the topic
- Checks for unreleased commits (commits since last tag)
- Runs semantic-release to bump version, update `plugin.toml`, create tag and GitHub release
- Version bumps based on conventional commits:
  - `fix:` → patch (0.0.x)
  - `feat:` → minor (0.x.0)
  - `<type>!:` or `BREAKING CHANGE:` in body → major (x.0.0)

Runs on push to main.
