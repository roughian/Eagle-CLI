# Changelog

This changelog summarizes the releases already reflected in the repository history and documentation.

## 0.9.0
- Added tag analysis and tag-normalization workflows, including alias-map based cleanup.
- Added saved selection sets plus report generation for library, tags, folders, and trends.
- Added declarative workflows, manifest-driven ingest, and incremental watch-based imports.
- Added plan merge/filter/split/validate/rollback helpers plus shell-completion and schema commands.
- Hardened session-state persistence with atomic writes and corrupted-session recovery.

## 0.8.0
- Expanded external CLI coverage with reusable plans, `--item-file`, `--last`, and `--all` selectors.
- Added `snapshot diff`, `audit dedupe-plan`, and `plan stats`.
- Extended `rename-bulk`, `move-bulk`, `organize apply`, and `snapshot restore` with stronger guardrails and reusable plan output.
- Added bridge-aware plan replay so mixed HTTP and bridge operations can be applied consistently.

## 0.7.0
- Added rollback and snapshot workflows.
- Added duplicate and cleanup auditing commands.
- Added bulk rename, bulk move, and higher-level organize workflows.
- Added a companion bridge plugin for deeper Eagle integration.

## 0.6.0
- Added `item stats` for distribution summaries across tags, folders, extensions, ratings, and note presence.
- Added bulk-update safety rails such as `--max-items`, `--require-match`, `--skip-unchanged`, and `--save-matches`.

## 0.5.0
- Added runnable smart-folder queries.
- Added preset bundle export and import.
- Added `item list --all` and item export formats for larger library workflows.

## 0.4.0
- Added library summaries and quick-access helpers.
- Added smart-folder inspection and rule auditing.
- Added tag-group inspection and richer batch item import workflows.
- Added repo migration support for the renamed workspace and persisted state.

## 0.3.0
- Added reusable search presets and operation plans.
- Added plan save/show/apply workflows.

## 0.2.0
- Improved packaging for GitHub installation and pipx usage.
- Added higher-level Eagle workflows and broader item/folder coverage.

## 0.1.0
- Initial Eagle CLI harness with core app, library, folder, and item commands.
