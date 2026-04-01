# TEST

## Plan

- Validate URL construction and API detection logic in the client.
- Validate representative CLI commands with mocks so tests do not modify the
  real Eagle library.
- Run a small live smoke check separately against read-only endpoints only.

## Commands

```bash
cd /Users/kim-wonseok/eagle-agent-harness
python3 -m unittest discover -s tests -v
python3 -m cli_anything.eagle.eagle_cli --json doctor
python3 -m cli_anything.eagle.eagle_cli --json app info
```

## Result

- `python3 -m unittest discover -s tests -v` passed with 6/6 tests.
- Live smoke checks passed for:
  - `cli-anything-eagle --json doctor`
  - `cli-anything-eagle --json app info`
  - `cli-anything-eagle --json item list --limit 2`
- Verified local Eagle API shape:
  - V1 endpoints responded successfully.
  - V2 endpoints were not available on the installed build.
