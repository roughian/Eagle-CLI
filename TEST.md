# TEST

## Plan

- Validate URL construction and API detection logic in the client.
- Validate representative CLI commands with mocks so tests do not modify the
  real Eagle library.
- Validate folder path resolution and batch-update planning.
- Run a small live smoke check separately against read-only endpoints only.

## Commands

```bash
cd /path/to/Eagle-CLI
python3 -m unittest discover -s tests -v
python3 -m cli_anything.eagle.eagle_cli --json doctor
python3 -m cli_anything.eagle.eagle_cli --json app info
python3 -m cli_anything.eagle.eagle_cli --json folder find Facebook --exact
python3 -m cli_anything.eagle.eagle_cli --json --dry-run item bulk-update --item-id EXAMPLE --add-tag reviewed
```

## Result

- `python3 -m unittest discover -s tests -v` passed.
- Live smoke checks passed for:
  - `cli-anything-eagle --json doctor`
  - `cli-anything-eagle --json app info`
  - `cli-anything-eagle --json item list --limit 2`
- Verified local Eagle API shape:
  - V1 endpoints responded successfully.
  - V2 endpoints were not available on the installed build.
