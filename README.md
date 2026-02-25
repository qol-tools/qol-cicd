# qol-tools

Organization-wide CI/CD workflows and shared standards.

## Workflows

### Auto-label qol-tray plugins

Adds the `qol-tray-plugin` topic when a repo starting with `plugin-` is created.

### Plugin version (reusable)

Reusable workflow at `.github/workflows/plugin-version.yml` for per-repo version bumps.

- Computes semver bump from conventional commits (`feat`/`fix`/`perf` and breaking changes only — `refactor`, `docs`, `chore`, `ci`, `style`, `test` are skipped)
- Updates `Cargo.toml` and `plugin.toml`
- Creates `chore(release): vX.Y.Z` commit
- Pushes release tag `vX.Y.Z`
- Exposes outputs: `should_release`, `version`, `bump`

Caller repos use:

```yaml
jobs:
  version:
    permissions:
      contents: write
    uses: qol-tools/qol-cicd/.github/workflows/plugin-version.yml@main
    with:
      cargo_manifest: Cargo.toml
      plugin_manifest: plugin.toml
      tag_prefix: v
```

### Test standards

Runs property tests for centralized standards in `standards/`.

### Release plugins (legacy)

Automatically releases all plugins with the `qol-tray-plugin` topic using semantic-release.

Runs on push to `main`.
