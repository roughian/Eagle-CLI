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
python3 -m cli_anything.eagle.eagle_cli --json audit dedupe-plan ./dedupe.json --keyword ui --mode name-size --keep largest
python3 -m cli_anything.eagle.eagle_cli --json plan stats ./dedupe.json
python3 -m cli_anything.eagle.eagle_cli --json bridge export-plugin ./bridge-plugin
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
```

## Result

- `python3 -m unittest discover -s tests -v` passed with 46 tests.
- Live smoke checks passed for:
  - `cli-anything-eagle --json doctor`
  - `cli-anything-eagle --json app info`
  - `cli-anything-eagle --json library summary`
  - `cli-anything-eagle --json bridge status`
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
  - `cli-anything-eagle --json audit dedupe-plan <tmp>/dedupe.json --keyword CleanShot --mode name --keep largest`
  - `cli-anything-eagle --json plan stats <tmp>/dedupe.json`
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
- Verified local Eagle API shape:
  - V1 endpoints responded successfully.
  - V2 endpoints were not available on the installed build.
- Verified live smart-folder rules currently expose:
  - properties: `type`, `folders`
  - methods: `equal`, `intersection`
- Verified live smart-folder execution:
  - `대화 jpg` translated cleanly into `ext=jpg` plus a single folder intersection.
