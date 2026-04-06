# TEST

## Plan

- Validate URL construction and API detection logic in the client.
- Validate representative CLI commands with mocks so tests do not modify the
  real Eagle library.
- Validate folder path resolution and batch-update planning.
- Validate preset persistence entry points, smart-folder summaries, and
  operation-plan replay commands.
- Validate smart-folder translation, preset bundle import/export, and item
  export pagination.
- Validate item stats summaries and bulk-update safety rails.
- Validate rollback snapshots, duplicate audits, bridge plugin export, and
  higher-level organize planning.
- Validate sequential `--last` reuse, `--item-file` selectors, snapshot diffs,
  bridge-aware plan replay, and duplicate trash plan generation.
- Validate selection-set persistence, report writers, tag normalization, and
  declarative workflow dry runs.
- Validate incremental watch planning plus shell-completion and schema helpers.
- Validate persistent config defaults and combined dashboard reporting.
- Validate bridge health summaries, doctor output, and cleanup dry runs.
- Validate plugin-backed selection reads, item opening, and live tag actions.
- Run a small live smoke check separately against read-only endpoints only.

## Commands

```bash
cd /path/to/CLI-Anything-Eagle
python3 -m unittest discover -s tests -v
python3 -m cli_anything.eagle.eagle_cli --json doctor
python3 -m cli_anything.eagle.eagle_cli --json app info
python3 -m cli_anything.eagle.eagle_cli --json library summary
python3 -m cli_anything.eagle.eagle_cli --json smart-folder audit
python3 -m cli_anything.eagle.eagle_cli --json smart-folder run --name "대화 jpg"
python3 -m cli_anything.eagle.eagle_cli --json folder find Facebook --exact
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item bulk-update --item-id EXAMPLE --add-tag reviewed
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item add-dir ./assets --recursive --ext png
python3 -m cli_anything.eagle.eagle_cli --json item export ./items.jsonl --all --limit 2 --keyword ui
python3 -m cli_anything.eagle.eagle_cli --json item stats --all --limit 2 --keyword ui
python3 -m cli_anything.eagle.eagle_cli --json preset export ./presets.json
python3 -m cli_anything.eagle.eagle_cli --json preset import ./presets.json --prefix imported-
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item bulk-update --keyword ui --add-tag reviewed --max-items 10 --save-matches ./matches.json
python3 -m cli_anything.eagle.eagle_cli --json snapshot create ./snapshot.json --item-id EXAMPLE
python3 -m cli_anything.eagle.eagle_cli --json snapshot show ./snapshot.json
python3 -m cli_anything.eagle.eagle_cli --json snapshot diff ./snapshot.json --include-names --include-folders
python3 -m cli_anything.eagle.eagle_cli --json --dry-run snapshot restore ./snapshot.json
python3 -m cli_anything.eagle.eagle_cli --json audit duplicates --all --top 5
python3 -m cli_anything.eagle.eagle_cli --json audit cleanup --all --sample-limit 5
python3 -m cli_anything.eagle.eagle_cli --json audit cleanup-plan ./cleanup.json --all --action add-tag
python3 -m cli_anything.eagle.eagle_cli --json audit dedupe-plan ./dedupe.json --keyword ui --mode name-size --keep largest
python3 -m cli_anything.eagle.eagle_cli --json plan stats ./dedupe.json
python3 -m cli_anything.eagle.eagle_cli --json tag stats --all --top 10
python3 -m cli_anything.eagle.eagle_cli --json tag audit --all --top 10
python3 -m cli_anything.eagle.eagle_cli --json --dry-run tag normalize --item-id EXAMPLE --trim --collapse-spaces
python3 -m cli_anything.eagle.eagle_cli --json select save review-set --item-id EXAMPLE
python3 -m cli_anything.eagle.eagle_cli --json select sample review-set --count 1 --resolve
python3 -m cli_anything.eagle.eagle_cli --json select diff review-set archived-set
python3 -m cli_anything.eagle.eagle_cli --json report tags ./report-tags.json --all --top 10
python3 -m cli_anything.eagle.eagle_cli --json report folders ./report-folders.json --all --top 10
python3 -m cli_anything.eagle.eagle_cli --json report trend ./report-trend.json --all --bucket month
python3 -m cli_anything.eagle.eagle_cli --json report dashboard ./dashboard.md --all --format md
python3 -m cli_anything.eagle.eagle_cli --json config show
python3 -m cli_anything.eagle.eagle_cli --json config set report_format md
python3 -m cli_anything.eagle.eagle_cli --json config unset report_format
python3 -m cli_anything.eagle.eagle_cli --json workflow validate ./workflow.yml
python3 -m cli_anything.eagle.eagle_cli --json --dry-run workflow run ./workflow.yml --save-plan ./workflow-plan.json
python3 -m cli_anything.eagle.eagle_cli --json plan validate ./workflow-plan.json
python3 -m cli_anything.eagle.eagle_cli --json plan filter ./workflow-plan.json ./workflow-http.json --kind http
python3 -m cli_anything.eagle.eagle_cli --json plan split ./workflow-plan.json ./plan-chunks --max-operations 10
python3 -m cli_anything.eagle.eagle_cli --json plan merge ./workflow-merged.json ./plan-chunks/*.json
python3 -m cli_anything.eagle.eagle_cli --json ingest manifest ./manifest.json
python3 -m cli_anything.eagle.eagle_cli --json --dry-run watch import-dir ./incoming --recursive --ext png --tag-from-name
python3 -m cli_anything.eagle.eagle_cli --json completion script --shell zsh --output ./completions/cli-anything-eagle.zsh
python3 -m cli_anything.eagle.eagle_cli --json schema show workflow --output ./schemas/workflow.json
python3 -m cli_anything.eagle.eagle_cli --json workflow template --list
python3 -m cli_anything.eagle.eagle_cli --json workflow template review-batch ./workflow.yml
python3 -m cli_anything.eagle.eagle_cli --json plan explain ./workflow-plan.json --output ./workflow-plan.md --format md
python3 -m cli_anything.eagle.eagle_cli --json report index ./report-index.json ./reports ./plans ./snapshots
python3 -m cli_anything.eagle.eagle_cli --json bridge export-plugin ./bridge-plugin
python3 -m cli_anything.eagle.eagle_cli --json bridge status
python3 -m cli_anything.eagle.eagle_cli --json bridge selected-item-ids
python3 -m cli_anything.eagle.eagle_cli --json bridge doctor --skip-ping
python3 -m cli_anything.eagle.eagle_cli --json --dry-run bridge cleanup --max-age-hours 0
python3 -m cli_anything.eagle.eagle_cli --json item selected
python3 -m cli_anything.eagle.eagle_cli --json folder selected
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item bulk-update --current-selection --add-tag reviewed
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item open --item-id EXAMPLE --window
python3 -m cli_anything.eagle.eagle_cli --json --dry-run tag rename-live "Old Tag" "New Tag"
python3 -m cli_anything.eagle.eagle_cli --json --dry-run tag merge-live "Legacy Tag" "Canonical Tag"
python3 -m cli_anything.eagle.eagle_cli --json item list --limit 2 --keyword CleanShot
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item bulk-update --last --add-tag reviewed
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item bulk-update --item-file ./items.json --add-tag reviewed
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item rename-bulk --item-id EXAMPLE --prefix archived- --save-plan ./rename.json
python3 -m cli_anything.eagle.eagle_cli item rename-bulk --help
python3 -m cli_anything.eagle.eagle_cli item move-bulk --help
python3 -m cli_anything.eagle.eagle_cli organize apply --help
python3 -m cli_anything.eagle.eagle_cli preset --help
python3 -m cli_anything.eagle.eagle_cli smart-folder --help
python3 -m cli_anything.eagle.eagle_cli plan --help
python3 -m cli_anything.eagle.eagle_cli workflow --help
python3 -m cli_anything.eagle.eagle_cli watch --help
python3 -m cli_anything.eagle.eagle_cli select --help
python3 -m cli_anything.eagle.eagle_cli tag --help
python3 -m cli_anything.eagle.eagle_cli config --help
python3 -m cli_anything.eagle.eagle_cli report dashboard --help
```

## Result

- `0.14.0` checks passed for:
  - `python3 -m unittest discover -s tests -v`
  - `node --check companion-plugin/plugin.js`
  - `node --check cli_anything/eagle/assets/companion-plugin/plugin.js`
  - `python3 -m cli_anything.eagle.eagle_cli --json workflow template --list`
  - `python3 -m cli_anything.eagle.eagle_cli --json workflow template review-batch <tmp>/workflow.yml`
  - `python3 -m cli_anything.eagle.eagle_cli --json plan explain <tmp>/plan.json --output <tmp>/plan.md --format md`
  - `python3 -m cli_anything.eagle.eagle_cli --json report index <tmp>/report-index.json <tmp>/inputs`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge selected-item-ids`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge select-items --selection smoke-selection`
  - `python3 -m cli_anything.eagle.eagle_cli --json --dry-run item bulk-update --current-selection --add-tag reviewed`
  - `python3 -m cli_anything.eagle.eagle_cli --json audit cleanup --current-selection --sample-limit 5`
  - `python3 -m cli_anything.eagle.eagle_cli --json tag stats --selection smoke-selection --top 10`
  - `python3 -m cli_anything.eagle.eagle_cli --json report tags <tmp>/report-tags-selection.json --selection smoke-selection --top 10`
  - isolated build env plus `python -m build`
  - fresh-venv install from the local repo plus `python -m cli_anything.eagle.eagle_cli --json bridge export-plugin <tmp>/plugin-copy`
- `0.12.2` live smoke checks passed for:
  - Eagle restart after `bridge install-plugin`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge status`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge ping --timeout 5`
  - `python3 -m cli_anything.eagle.eagle_cli --json item selected`
  - `python3 -m cli_anything.eagle.eagle_cli --json folder selected`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge doctor`
- `0.12.1` smoke checks passed for:
  - `python3 -m py_compile cli_anything/eagle/eagle_cli.py cli_anything/eagle/core/bridge.py cli_anything/eagle/core/client.py tests/test_cli.py tests/test_client.py`
  - `node --check companion-plugin/plugin.js`
  - `python3 -m cli_anything.eagle.eagle_cli --version`
  - `python3 -m cli_anything.eagle.eagle_cli --json app info`
  - `python3 -m cli_anything.eagle.eagle_cli --json doctor`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge status`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge doctor --skip-ping`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge install-plugin`
  - `python3 -m cli_anything.eagle.eagle_cli --json --dry-run bridge cleanup --max-age-hours 0 --requests`
  - `python3 -m cli_anything.eagle.eagle_cli --json bridge cleanup --max-age-hours 0 --keep-last 0 --requests --no-responses --no-processed`
- Full `CliRunner`-based unittest runs passed with 89 tests.
- Live smoke checks passed for:
  - `cli-anything-eagle --json doctor`
  - `cli-anything-eagle --json app info`
  - `cli-anything-eagle --json library summary`
  - `cli-anything-eagle --json bridge status`
  - `cli-anything-eagle --json bridge doctor --skip-ping`
  - `cli-anything-eagle --json --dry-run bridge cleanup --max-age-hours 0`
  - `cli-anything-eagle --json item selected`
  - `cli-anything-eagle --json folder selected`
  - `cli-anything-eagle --json smart-folder audit`
  - `cli-anything-eagle --json smart-folder rules --name "대화 jpg"`
  - `cli-anything-eagle --json smart-folder run --name "대화 jpg"`
  - `cli-anything-eagle --json item list --limit 2`
  - `cli-anything-eagle --json snapshot create <tmp>/snapshot.json --item-id <id>`
  - `cli-anything-eagle --json snapshot show <tmp>/snapshot.json`
  - `cli-anything-eagle --json snapshot diff <tmp>/snapshot.json --include-names --include-folders`
  - `cli-anything-eagle --json --dry-run snapshot restore <tmp>/snapshot.json`
  - `cli-anything-eagle --json --dry-run item add-dir <tmp> --recursive --ext png`
  - `cli-anything-eagle --json item list --limit 2 --keyword CleanShot`
  - `cli-anything-eagle --json --dry-run item bulk-update --last --add-tag reviewed`
  - `cli-anything-eagle --json --dry-run item bulk-update --item-file <tmp>/items.json --add-tag reviewed`
  - `cli-anything-eagle --json --dry-run item rename-bulk --item-id <id> --prefix archived-`
  - `cli-anything-eagle --json plan stats <tmp>/rename-plan.json`
  - `cli-anything-eagle --json --dry-run item move-bulk --item-id <id> --target-folder-path <path>`
  - `cli-anything-eagle --json item export <tmp>/items.jsonl --all --limit 2 --keyword ui`
  - `cli-anything-eagle --json item stats --all --limit 2 --keyword ui`
  - `cli-anything-eagle --json audit duplicates --all --top 5`
  - `cli-anything-eagle --json audit cleanup --all --sample-limit 5`
  - `cli-anything-eagle --json audit cleanup-plan <tmp>/cleanup.json --all --action add-tag`
  - `cli-anything-eagle --json audit dedupe-plan <tmp>/dedupe.json --keyword CleanShot --mode name --keep largest`
  - `cli-anything-eagle --json plan stats <tmp>/dedupe.json`
  - `cli-anything-eagle --json tag stats --all --top 10`
  - `cli-anything-eagle --json select save smoke-selection --item-id <id>`
  - `cli-anything-eagle --json select sample smoke-selection --count 1 --resolve`
  - `cli-anything-eagle --json config show`
  - `cli-anything-eagle --json report dashboard <tmp>/dashboard.md --limit 1 --format md`
  - `cli-anything-eagle --json --dry-run workflow run <tmp>/workflow.yml --save-plan <tmp>/workflow-plan.json`
  - `cli-anything-eagle --json plan validate <tmp>/workflow-plan.json`
  - `cli-anything-eagle --json --dry-run watch import-dir <tmp> --ext png --tag review --tag-from-name`
  - `cli-anything-eagle --json completion script --shell zsh --output <tmp>/cli-anything-eagle.zsh`
  - `cli-anything-eagle --json schema show workflow --output <tmp>/workflow-schema.json`
  - `cli-anything-eagle --json preset export <tmp>/presets.json`
  - `cli-anything-eagle --json preset import <tmp>/presets.json --prefix imported-`
  - `cli-anything-eagle --json --dry-run item bulk-update --keyword ui --add-tag reviewed --max-items 10 --save-matches <tmp>/matches.json`
  - `cli-anything-eagle --json --dry-run organize apply --item-id <id> --add-tag reviewed --name-prefix ui-`
  - `cli-anything-eagle --json bridge export-plugin <tmp>/bridge-plugin`
  - `cli-anything-eagle --dry-run item bulk-update --keyword ui --add-tag reviewed --max-items 1` correctly failed
  - `cli-anything-eagle --json --dry-run preset run-bulk-update review-ui`
  - `cli-anything-eagle item rename-bulk --help`
  - `cli-anything-eagle item move-bulk --help`
  - `cli-anything-eagle organize apply --help`
  - `cli-anything-eagle preset --help`
  - `cli-anything-eagle smart-folder --help`
  - `cli-anything-eagle plan --help`
  - `cli-anything-eagle workflow --help`
  - `cli-anything-eagle watch --help`
  - `cli-anything-eagle select --help`
  - `cli-anything-eagle tag --help`
  - `cli-anything-eagle config --help`
  - `cli-anything-eagle report dashboard --help`
- Verified local Eagle API shape:
  - V1 endpoints responded successfully.
  - V2 endpoints were not available on the installed build.
- Verified live smart-folder rules currently expose:
  - properties: `type`, `folders`
  - methods: `equal`, `intersection`
- Verified live smart-folder execution:
  - `대화 jpg` translated cleanly into `ext=jpg` plus a single folder intersection.
