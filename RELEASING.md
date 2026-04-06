# Releasing

Use this checklist when cutting a new `cli-anything-eagle` release.

## Local Validation

```bash
python3 -m pip install -e ".[dev]"
python3 -m unittest discover -s tests -v
node --check companion-plugin/plugin.js
node --check cli_anything/eagle/assets/companion-plugin/plugin.js
python3 -m build
```

## Fresh Install Smoke Test

```bash
tmpdir=$(mktemp -d)
python3 -m venv "$tmpdir/venv"
"$tmpdir/venv/bin/pip" install .
"$tmpdir/venv/bin/python" -m cli_anything.eagle.eagle_cli --version
"$tmpdir/venv/bin/python" -m cli_anything.eagle.eagle_cli --json bridge export-plugin "$tmpdir/plugin-copy"
```

## Publish

1. Update versioned files:
   - `cli_anything/eagle/__init__.py`
   - `pyproject.toml`
   - `companion-plugin/manifest.json`
   - `companion-plugin/plugin.js`
   - `cli_anything/eagle/assets/companion-plugin/manifest.json`
   - `cli_anything/eagle/assets/companion-plugin/plugin.js`
2. Update `CHANGELOG.md` and `TEST.md`.
3. Commit the release.
4. Create and push a tag:

```bash
git tag vX.Y.Z
git push origin main --tags
```

5. Draft the GitHub release notes from the matching `CHANGELOG.md` section.
