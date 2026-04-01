# CLI-Anything Eagle

`cli-anything-eagle` is a broad CLI harness for the Eagle desktop app on macOS.
It targets Eagle's local HTTP API and exposes high-value commands for app info,
library management, folders, items, and raw requests for unsupported endpoints.

## Install

```bash
cd /Users/kim-wonseok/eagle-agent-harness
pip install -e .
```

## Requirements

- Eagle desktop app running locally
- Eagle API listening on `http://localhost:41595`
- Python 3.10+

## Quick start

```bash
cli-anything-eagle doctor
cli-anything-eagle app info
cli-anything-eagle library info
cli-anything-eagle folder tree
cli-anything-eagle --json item list --limit 10 --tag reference
```

## Covered commands

- `doctor`
- `app info`
- `library info`, `history`, `switch`, `icon`
- `folder list`, `tree`, `recent`, `create`, `rename`, `update`
- `item list`, `info`, `thumbnail`, `update`
- `item add-path`, `add-paths`, `add-url`, `add-urls`, `add-bookmark`
- `item trash`, `refresh-palette`, `refresh-thumbnail`
- `raw request`

## Notes

- This harness targets the Eagle API variant that was verified locally:
  `GET /api/application/info`, `GET /api/library/info`, `GET /api/folder/list`,
  and `GET /api/item/list`.
- Newer Eagle Web API v2 docs also exist, but this harness is optimized for the
  API that actually responded on the current machine.
