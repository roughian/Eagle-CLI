# CLI-Anything Eagle

`cli-anything-eagle` is a broad command-line interface for the Eagle desktop app.
It targets Eagle's local HTTP API and exposes practical commands for app info,
library management, folder workflows, smart-folder rule inspection, item
ingestion, bulk edits, reusable presets, preset bundles, item export, operation
plans, and low-level escape hatches.

## Requirements

- Eagle desktop app running locally
- Eagle API listening on `http://localhost:41595`
- Python 3.10+

## Install

Recommended for general users:

```bash
python3 -m pip install "git+https://github.com/roughian/CLI-Anything-Eagle.git"
```

Recommended for a cleaner CLI-only install:

```bash
pipx install "git+https://github.com/roughian/CLI-Anything-Eagle.git"
```

For local development:

```bash
git clone https://github.com/roughian/CLI-Anything-Eagle.git
cd CLI-Anything-Eagle
python3 -m pip install -e .
```

If the `cli-anything-eagle` script is not on your shell `PATH`, you can still run:

```bash
python3 -m cli_anything.eagle.eagle_cli --help
```

## Quick Start

```bash
cli-anything-eagle doctor
cli-anything-eagle app info
cli-anything-eagle library summary
cli-anything-eagle library info
cli-anything-eagle smart-folder audit
cli-anything-eagle smart-folder run --name "Camera JPG"
cli-anything-eagle folder tree
cli-anything-eagle folder find Reference
cli-anything-eagle --json item list --limit 10 --tag reference
```

## Useful Workflows

Inspect the local Eagle API and version:

```bash
cli-anything-eagle doctor
cli-anything-eagle --json app info
cli-anything-eagle --json library summary
cli-anything-eagle --json smart-folder audit
```

Find and prepare folders by name or path:

```bash
cli-anything-eagle folder find Inspiration
cli-anything-eagle --dry-run folder ensure-path "Design/UI/References"
cli-anything-eagle folder ensure-path "Design/UI/References"
```

Target items by folder path, not just folder ID:

```bash
cli-anything-eagle item list --folder-path "Design/UI/References" --limit 20
cli-anything-eagle item add-path ./shot.png --folder-path "Design/UI/References"
```

Inspect smart-folder rules and variables already used inside Eagle:

```bash
cli-anything-eagle smart-folder list
cli-anything-eagle smart-folder rules --name "Camera JPG"
cli-anything-eagle --json smart-folder audit
```

Run supported smart-folder rules as a real item query:

```bash
cli-anything-eagle --json smart-folder run --name "Camera JPG"
cli-anything-eagle smart-folder run --name "Camera JPG" --limit 100 --save-preset camera-jpg
```

Preview batch edits safely before applying them:

```bash
cli-anything-eagle --dry-run item bulk-update \
  --folder-name References \
  --keyword icon \
  --add-tag reviewed

cli-anything-eagle item bulk-update \
  --folder-name References \
  --keyword icon \
  --add-tag reviewed
```

Save reusable bulk-update presets and replay them later:

```bash
cli-anything-eagle preset save-bulk-update review-ui \
  --keyword ui \
  --add-tag reviewed

cli-anything-eagle --dry-run preset run-bulk-update review-ui
cli-anything-eagle preset run-bulk-update review-ui
```

Share presets with other Eagle users:

```bash
cli-anything-eagle preset export ./bundles/team-presets.json review-ui ui-ref
cli-anything-eagle preset import ./bundles/team-presets.json --prefix team-
```

Save and reuse frequent searches:

```bash
cli-anything-eagle preset save-item-list ui-ref \
  --keyword ui \
  --tag reference \
  --folder-path "Design/UI/References"

cli-anything-eagle preset list
cli-anything-eagle preset run-item-list ui-ref
```

Add a whole local directory with filtering and a saved manifest:

```bash
cli-anything-eagle --dry-run item add-dir ./assets \
  --recursive \
  --ext png \
  --folder-path "Design/UI/References" \
  --save-manifest ./manifests/assets.json

cli-anything-eagle item add-dir ./assets --recursive --glob "*.png"
```

Fetch all matching items and export them:

```bash
cli-anything-eagle item list --all --limit 100 --keyword ui
cli-anything-eagle item export ./exports/ui-items.jsonl --all --limit 100 --keyword ui
cli-anything-eagle item export ./exports/ui-items.csv --format csv --folder-path "Design/UI/References"
```

Export mutation plans and apply them later:

```bash
cli-anything-eagle --dry-run item bulk-update \
  --folder-path "Design/UI/References" \
  --add-tag reviewed \
  --save-plan ./plans/reviewed.json

cli-anything-eagle plan show ./plans/reviewed.json
cli-anything-eagle plan apply ./plans/reviewed.json
```

## Covered Commands

- `doctor`
- `app info`
- `library info`, `history`, `switch`, `icon`, `summary`, `quick-access`
- `smart-folder list`, `tree`, `show`, `rules`, `audit`, `run`
- `tag-group list`, `show`
- `folder list`, `tree`, `find`, `recent`, `create`, `ensure`, `ensure-path`, `rename`, `update`
- `item list`, `export`, `info`, `thumbnail`, `update`, `bulk-update`
- `item add-path`, `add-paths`, `add-dir`, `add-url`, `add-urls`, `add-bookmark`
- `item trash`, `refresh-palette`, `refresh-thumbnail`
- `preset list`, `show`, `delete`, `export`, `import`, `save-item-list`, `run-item-list`, `save-bulk-update`, `run-bulk-update`
- `plan show`, `save-last`, `apply`
- `raw request`

## Notes

- This harness targets the Eagle API variant verified locally:
  `GET /api/application/info`, `GET /api/library/info`, `GET /api/folder/list`,
  and `GET /api/item/list`.
- Newer Eagle Web API v2 docs also exist, but this project is optimized for the
  API that actually responded on the tested Eagle build.
- The CLI stores session state and presets in `~/.config/cli-anything-eagle`.
  Existing `~/.config/eagle-agent-harness` state is read as a legacy fallback.
- `smart-folder run` is intentionally conservative. If Eagle rules include
  unsupported logic such as non-`AND` groups, it will stop unless you
  explicitly pass `--allow-partial`.
- Mutating commands support `--dry-run`, which is useful when sharing the CLI
  with other Eagle users who want to preview changes first.
