# CLI-Anything Eagle

`cli-anything-eagle` is a broad command-line interface for the Eagle desktop app.
It targets Eagle's local HTTP API and exposes practical commands for app info,
library management, folder workflows, item ingestion, bulk edits, and low-level
escape hatches.

## Requirements

- Eagle desktop app running locally
- Eagle API listening on `http://localhost:41595`
- Python 3.10+

## Install

Recommended for general users:

```bash
python3 -m pip install "git+https://github.com/roughian/Eagle-CLI.git"
```

Recommended for a cleaner CLI-only install:

```bash
pipx install "git+https://github.com/roughian/Eagle-CLI.git"
```

For local development:

```bash
git clone https://github.com/roughian/Eagle-CLI.git
cd Eagle-CLI
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
cli-anything-eagle library info
cli-anything-eagle folder tree
cli-anything-eagle folder find Reference
cli-anything-eagle --json item list --limit 10 --tag reference
```

## Useful Workflows

Inspect the local Eagle API and version:

```bash
cli-anything-eagle doctor
cli-anything-eagle --json app info
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

## Covered Commands

- `doctor`
- `app info`
- `library info`, `history`, `switch`, `icon`
- `folder list`, `tree`, `find`, `recent`, `create`, `ensure`, `ensure-path`, `rename`, `update`
- `item list`, `info`, `thumbnail`, `update`, `bulk-update`
- `item add-path`, `add-paths`, `add-url`, `add-urls`, `add-bookmark`
- `item trash`, `refresh-palette`, `refresh-thumbnail`
- `raw request`

## Notes

- This harness targets the Eagle API variant verified locally:
  `GET /api/application/info`, `GET /api/library/info`, `GET /api/folder/list`,
  and `GET /api/item/list`.
- Newer Eagle Web API v2 docs also exist, but this project is optimized for the
  API that actually responded on the tested Eagle build.
- Mutating commands support `--dry-run`, which is useful when sharing the CLI
  with other Eagle users who want to preview changes first.
