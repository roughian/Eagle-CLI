# CLI-Anything Eagle

`cli-anything-eagle` is a broad command-line interface for the Eagle desktop
app. It targets Eagle's local HTTP API and exposes practical commands for app
info, library management, folder workflows, smart-folder rule inspection, item
ingestion, bulk edits, reusable presets, preset bundles, item export,
operation plans, query stats, rollback snapshots, snapshot diffs, duplicate and
cleanup audits, duplicate cleanup plan generation, tag audits and normalization,
saved selection sets, reusable reports, declarative workflows, manifest-driven
ingestion, incremental import watching, plan merge/filter/split/validate
tooling, shell-completion helpers, document schemas, persistent config defaults,
dashboard reports, high-level organize flows,
and a companion bridge plugin for selection, open, tag, name, and folder
operations that are not available through the local HTTP API alone, plus bridge
health diagnostics and cleanup helpers.

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
cli-anything-eagle --json audit duplicates --all --top 5
cli-anything-eagle --json audit dedupe-plan ./plans/duplicates.json --keyword logo
cli-anything-eagle --json plan stats ./plans/duplicates.json
cli-anything-eagle --json tag stats --all --top 10
cli-anything-eagle --json select list
cli-anything-eagle --json config show
cli-anything-eagle report dashboard ./reports/dashboard.md --format md --all
cli-anything-eagle --json workflow validate ./workflow.yml
cli-anything-eagle --json bridge status
cli-anything-eagle --json bridge doctor --skip-ping
cli-anything-eagle --json item selected
cli-anything-eagle --json folder selected
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

Inspect filtered items before mutating them:

```bash
cli-anything-eagle item stats --all --limit 50 --keyword ui
cli-anything-eagle item stats --folder-path "Design/UI/References" --top 20
```

Add safety rails to bulk updates:

```bash
cli-anything-eagle --dry-run item bulk-update \
  --keyword ui \
  --add-tag reviewed \
  --max-items 10 \
  --require-match 1 \
  --save-matches ./exports/ui-matches.json

cli-anything-eagle --dry-run item bulk-update \
  --item-id EXAMPLE \
  --add-tag reviewed \
  --skip-unchanged
```

Reuse the last item-producing command or load item IDs from a file:

```bash
cli-anything-eagle --json item list --limit 20 --keyword CleanShot
cli-anything-eagle --dry-run item bulk-update --last --add-tag reviewed

cli-anything-eagle item export ./exports/cleanshot.json --limit 20 --keyword CleanShot
cli-anything-eagle --dry-run item bulk-update --item-file ./exports/cleanshot.json --add-tag reviewed
```

Create rollback snapshots before bigger changes:

```bash
cli-anything-eagle snapshot create ./snapshots/ui.json --folder-path "Design/UI/References"
cli-anything-eagle snapshot show ./snapshots/ui.json
cli-anything-eagle snapshot diff ./snapshots/ui.json --include-names --include-folders
cli-anything-eagle --dry-run snapshot restore ./snapshots/ui.json
```

Rename or move many items with the companion bridge plugin:

```bash
cli-anything-eagle bridge install-plugin
cli-anything-eagle --json bridge status
cli-anything-eagle --json bridge doctor --skip-ping
cli-anything-eagle --json --dry-run bridge cleanup --max-age-hours 24
cli-anything-eagle --json item selected
cli-anything-eagle --json folder selected
cli-anything-eagle --dry-run item open --item-id EXAMPLE --window
cli-anything-eagle --dry-run tag rename-live "Old Tag" "New Tag"
cli-anything-eagle --dry-run tag merge-live "Legacy Tag" "Canonical Tag"
cli-anything-eagle --dry-run item rename-bulk --folder-name References --prefix archived-
cli-anything-eagle --dry-run item move-bulk --tag reviewed --target-folder-path "Archive/Reviewed"
```

Audit duplicate candidates and cleanup hotspots:

```bash
cli-anything-eagle --json audit duplicates --all --mode name --mode url --top 20
cli-anything-eagle --json audit cleanup --all --sample-limit 10
cli-anything-eagle --json audit dedupe-plan ./plans/duplicate-trash.json --keyword ui --mode name-size --keep largest
cli-anything-eagle --json plan stats ./plans/duplicate-trash.json
```

Run a higher-level organize workflow in one command:

```bash
cli-anything-eagle --dry-run organize apply \
  --folder-path "Design/UI/References" \
  --add-tag reviewed \
  --name-prefix ui- \
  --ensure-target-path "Archive/UI Reviewed" \
  --max-items 100 \
  --save-snapshot ./snapshots/ui-reviewed.json
```

Export mutation plans and apply them later:

```bash
cli-anything-eagle --dry-run item bulk-update \
  --folder-path "Design/UI/References" \
  --add-tag reviewed \
  --save-plan ./plans/reviewed.json

cli-anything-eagle plan show ./plans/reviewed.json
cli-anything-eagle plan stats ./plans/reviewed.json
cli-anything-eagle plan apply ./plans/reviewed.json
```

Bridge-backed plans work too:

```bash
cli-anything-eagle --dry-run item rename-bulk \
  --item-file ./exports/cleanshot.json \
  --prefix archived- \
  --save-plan ./plans/rename.json

cli-anything-eagle plan stats ./plans/rename.json
cli-anything-eagle plan apply ./plans/rename.json
```

Audit and normalize tags before large cleanup passes:

```bash
cli-anything-eagle --json tag stats --all --top 25
cli-anything-eagle --json tag audit --all --top 25
cli-anything-eagle --dry-run tag normalize \
  --all \
  --trim \
  --collapse-spaces \
  --save-plan ./plans/normalize-tags.json

cli-anything-eagle --dry-run tag alias-map-apply ./tag-aliases.yaml \
  --all \
  --save-plan ./plans/tag-aliases.json
```

Save and compare reusable item selections:

```bash
cli-anything-eagle select save review-set --keyword review --all
cli-anything-eagle select sample review-set --count 10 --resolve
cli-anything-eagle select diff review-set archived-set
cli-anything-eagle select save-current live-selection
```

Generate reusable reports and workflow plans:

```bash
cli-anything-eagle report library ./reports/library.md --format md
cli-anything-eagle report tags ./reports/tags.csv --all --top 100 --format csv
cli-anything-eagle report folders ./reports/folders.md --all --format md
cli-anything-eagle report trend ./reports/trend.json --all --bucket month --field modification

cli-anything-eagle workflow validate ./workflow.yml
cli-anything-eagle --dry-run workflow run ./workflow.yml --save-plan ./plans/workflow.json
cli-anything-eagle plan validate ./plans/workflow.json
cli-anything-eagle plan split ./plans/workflow.json ./plans/chunks --max-operations 25
cli-anything-eagle plan merge ./plans/all.json ./plans/chunks/*.json
```

Use manifests, incremental watching, shell completion, and built-in schemas:

```bash
cli-anything-eagle ingest manifest ./manifests/assets.json --folder-path "Design/UI/References"
cli-anything-eagle --dry-run watch import-dir ./incoming --recursive --ext png --tag-from-name
cli-anything-eagle completion script --shell zsh --output ./completions/cli-anything-eagle.zsh
cli-anything-eagle schema show workflow --output ./schemas/workflow.json
```

Persist shared CLI defaults once and reuse them everywhere:

```bash
cli-anything-eagle config set report_format md
cli-anything-eagle config set export_format jsonl
cli-anything-eagle config set completion_shell fish
cli-anything-eagle config show
cli-anything-eagle config unset completion_shell
```

## Covered Commands

- `doctor`
- `config path`, `show`, `set`, `unset`
- `app info`
- `library info`, `history`, `switch`, `icon`, `summary`, `quick-access`
- `smart-folder list`, `tree`, `show`, `rules`, `audit`, `run`
- `tag stats`, `audit`, `rename`, `normalize`, `alias-map-apply`
- `tag rename-live`, `merge-live`
- `tag-group list`, `show`
- `folder list`, `tree`, `find`, `selected`, `open`, `recent`, `create`, `ensure`, `ensure-path`, `rename`, `update`
- `item list`, `selected`, `select`, `open`, `export`, `stats`, `info`, `thumbnail`, `update`, `bulk-update`, `rename-bulk`, `move-bulk`
- `item add-path`, `add-paths`, `add-dir`, `add-url`, `add-urls`, `add-bookmark`
- `item trash`, `refresh-palette`, `refresh-thumbnail`
- `select list`, `save`, `show`, `delete`, `sample`, `diff`
- `report library`, `tags`, `folders`, `trend`
- `report dashboard`
- `preset list`, `show`, `delete`, `export`, `import`, `save-item-list`, `run-item-list`, `save-bulk-update`, `run-bulk-update`
- `snapshot create`, `show`, `diff`, `restore`
- `audit duplicates`, `cleanup`, `cleanup-plan`, `dedupe-plan`
- `organize apply`
- `bridge status`, `doctor`, `context`, `open-folder`, `select-items`, `cleanup`, `export-plugin`, `install-plugin`, `ping`
- `workflow validate`, `run`
- `ingest manifest`
- `watch import-dir`
- `completion script`
- `schema show`
- `plan show`, `stats`, `save-last`, `apply`, `merge`, `split`, `filter`, `explain`, `validate`, `rollback-from-results`
- `raw request`

## Notes

- This harness targets the Eagle API variant verified locally:
  `GET /api/application/info`, `GET /api/library/info`, `GET /api/folder/list`,
  and `GET /api/item/list`.
- Newer Eagle Web API v2 docs also exist, but this project is optimized for the
  API that actually responded on the tested Eagle build.
- The CLI stores session state and presets in `~/.config/cli-anything-eagle`.
  Existing `~/.config/eagle-agent-harness` state is read as a legacy fallback.
- Session-state writes are now atomic, and a corrupted session file is moved
  aside as `session.corrupt-<timestamp>.json` on the next load instead of
  crashing the CLI.
- Presets, plans, reports, manifests, bridge requests, and watch-state files
  also use atomic writes so long-running or concurrent CLI usage is less likely
  to leave partial JSON behind.
- `--last` reuses item IDs from the immediately previous item-producing command
  recorded in session state. It is best used in sequential workflows rather
  than parallel command runs.
- `smart-folder run` is intentionally conservative. If Eagle rules include
  unsupported logic such as non-`AND` groups, it will stop unless you
  explicitly pass `--allow-partial`.
- `item bulk-update` can now enforce safety boundaries with `--max-items`,
  `--require-match`, `--skip-unchanged`, and `--save-matches`.
- `item bulk-update`, `rename-bulk`, `move-bulk`, `organize apply`, and
  `snapshot restore` can all save reusable plans. `plan apply` now supports
  both direct HTTP operations and bridge-backed rename or move operations.
- `snapshot` files are plain JSON documents, so you can archive them with your
  own backups or review them before any restore.
- `audit dedupe-plan` only writes a reusable trash plan; it never deletes or
  trashes anything by itself.
- `item rename-bulk`, `item move-bulk`, and `organize apply` rely on the
  companion bridge plugin when names or folder assignments must change through
  Eagle's Plugin API instead of the local HTTP API.
- `bridge install-plugin` copies the bundled service plugin into Eagle's plugin
  directory. When no explicit plugin directory is passed, it now refreshes all
  detected Eagle plugin roots. If Eagle is already open, restart it once so the
  background bridge can start.
- `bridge status` and `bridge doctor` now summarize heartbeat freshness, queue
  backlog, writable bridge directories, and whether the installed plugin build
  matches the current CLI version.
- `item selected` and `folder selected` read the current Eagle UI selection
  through the companion plugin. `item open`, `tag rename-live`, and
  `tag merge-live` also require the plugin bridge to be active.
- `bridge cleanup` only removes old bridge request/response artifacts. Use
  `--dry-run` first if you want to preview which files would be pruned.
- Mutating commands support `--dry-run`, which is useful when sharing the CLI
  with other Eagle users who want to preview changes first.
