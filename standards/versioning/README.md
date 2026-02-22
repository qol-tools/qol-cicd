# Versioning Standard

`next_version.py` defines shared version bump semantics for QoL Tray repos.

Rules:
- release commits matching `chore(release): v...` are ignored for bump detection
- any breaking change (`type(scope)!:` or `BREAKING CHANGE:` footer/body) bumps `major`
- any `feat:` without breaking bumps `minor`
- otherwise bump `patch`
- if the computed tag already exists, increment patch until a free tag is found

Run tests:

```bash
python3 -m pip install -r standards/versioning/requirements-dev.txt
python3 -m pytest standards/versioning/tests -n auto --dist worksteal -v --no-header --no-summary
```

CLI modes:

```bash
python3 standards/versioning/next_version.py eval \
  --base-version 1.2.3 \
  --commits-json /path/to/commits.json \
  --existing-tags-json /path/to/tags.json
```

```bash
python3 standards/versioning/next_version.py git \
  --repo . \
  --from-ref v1.2.3 \
  --output-format github \
  --github-output "$GITHUB_OUTPUT"
```
