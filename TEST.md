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
python3 -m cli_anything.eagle.eagle_cli preset --help
python3 -m cli_anything.eagle.eagle_cli smart-folder --help
python3 -m cli_anything.eagle.eagle_cli plan --help
```

## Result

- `python3 -m unittest discover -s tests -v` passed with 34 tests.
- Live smoke checks passed for:
  - `cli-anything-eagle --json doctor`
  - `cli-anything-eagle --json app info`
  - `cli-anything-eagle --json library summary`
  - `cli-anything-eagle --json smart-folder audit`
  - `cli-anything-eagle --json smart-folder rules --name "대화 jpg"`
  - `cli-anything-eagle --json smart-folder run --name "대화 jpg"`
  - `cli-anything-eagle --json item list --limit 2`
  - `cli-anything-eagle --json --dry-run item add-dir <tmp> --recursive --ext png`
  - `cli-anything-eagle --json item export <tmp>/items.jsonl --all --limit 2 --keyword ui`
  - `cli-anything-eagle --json item stats --all --limit 2 --keyword ui`
  - `cli-anything-eagle --json preset export <tmp>/presets.json`
  - `cli-anything-eagle --json preset import <tmp>/presets.json --prefix imported-`
  - `cli-anything-eagle --json --dry-run item bulk-update --keyword ui --add-tag reviewed --max-items 10 --save-matches <tmp>/matches.json`
  - `cli-anything-eagle --dry-run item bulk-update --keyword ui --add-tag reviewed --max-items 1` correctly failed
  - `cli-anything-eagle --json --dry-run preset run-bulk-update review-ui`
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
