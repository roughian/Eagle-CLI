# Changelog

This changelog summarizes the releases already reflected in the repository history and documentation.

## 0.17.0
- Added `agent observe` to turn the live Eagle context into a reusable observation report with bridge, cleanup, and tag summaries.
- Added `agent plan` so AI-safe plans can be built from the current selection, the current folder, saved selectors, and move-to-current-folder targets before any mutation happens.
- Added `agent apply` to execute saved agent plans with optional verification and saved result manifests, and `agent verify` to re-check convergence after the run.
- Hardened the new observation path so `agent observe` still succeeds when Eagle's library metadata endpoint is temporarily unavailable.

## 0.16.0
- Added `select save-current-folder`, `item move-to-current-folder`, and `report current-context` so plugin-backed Eagle UI state can be turned into saved selections, reports, and move targets without copying folder IDs by hand.
- Promoted the companion bridge `get_context` response into shared CLI helpers for current-folder resolution, so `folder selected` and other current-context flows resolve stable folder paths when the local HTTP API knows them.
- Extended workflow file selection support with saved selections, `current_selection`, and `current_folder` so declarative runs can target the live Eagle UI state through the companion plugin.
- Synchronized the CLI and bundled companion-plugin versions after the current-context workflow expansion.

## 0.15.0
- Added plugin-backed `app show` so the CLI can bring Eagle's main window to the front through the companion bridge when the runtime supports `eagle.app.show()`.
- Added plugin-backed `tag recent-live` and `tag starred-live` to surface Eagle's recent and starred tags directly from the Plugin API.
- Synchronized the bundled companion-plugin asset with the repo plugin so packaged installs keep the same bridge heartbeat, library-summary caching, and live action support.

## 0.14.0
- Added `workflow template` so common review, reporting, and archive flows can be scaffolded as ready-to-edit YAML or JSON workflow files.
- Expanded `plan explain` into a richer summary surface with operation breakdowns and optional saved Markdown/HTML/JSON/CSV explanations.
- Added `report index` to catalog existing plans, snapshots, workflows, manifests, and reports into a reusable inventory document.

## 0.13.1
- Extended saved-selection and current-selection targeting across tag workflows, audit reports, and report generation commands instead of limiting selection-aware flows to item mutations.
- Added a companion-plugin compatibility fallback so single-item `bridge select-items` can attempt `open()` on older runtimes and report the actual post-fallback selection state instead of assuming success.
- Added regression coverage for plugin-backed `audit cleanup --current-selection` plus saved-selection support in `tag stats` and `report tags`.
- Synchronized the CLI, packaged plugin assets, and companion-plugin manifest versions after the selection-surface expansion.

## 0.13.0
- Bundled the companion bridge plugin template inside the Python package so `bridge export-plugin` and `bridge install-plugin` keep working from non-editable `pip` and `pipx` installs.
- Added the missing `get_selected_item_ids` bridge action plus a new `bridge selected-item-ids` command, which restores `--current-selection` workflows across bulk-update, rename, move, organize, and saved-selection commands.
- Continued the CLI cleanup by routing saved-selection persistence through the dedicated core selection module instead of duplicated inline helpers.

## 0.12.2
- Reduced bridge heartbeat payloads so `status.json`, `bridge status`, and `bridge ping` report compact library summaries instead of the full Eagle folder tree.
- Kept the companion plugin version aligned with the CLI after the live-bridge restart verification pass.
- Consumed bridge response files now get cleaned up after reads so `bridge doctor` no longer reports a false queue backlog during normal use.

## 0.12.1
- Stopped bridge read/diagnostic commands from stalling on import by deferring optional file-copy and HTTP-client setup until those paths are actually used.
- Added lazy `AppContext.client` creation so local-only commands such as `bridge status`, `bridge doctor --skip-ping`, and `bridge cleanup` can run without initializing the Eagle HTTP backend.
- Switched the default `EagleClient` transport to a curl-backed exec path while still supporting injected mock/session objects in tests.
- Synchronized the companion plugin version with the CLI and added a persistent `plugin.log` bridge log for post-restart diagnostics.
- Added regression coverage for the lazy client path and bridge-local command behavior.

## 0.12.0
- Expanded the companion plugin with item-open and tag-rename/tag-merge bridge actions, plus safer atomic writes for plugin status and responses.
- Added plugin-backed `item selected`, `item open`, `folder selected`, `tag rename-live`, and `tag merge-live` commands so Eagle UI state can be inspected and controlled directly from the CLI.
- Updated `bridge install-plugin` to refresh every detected Eagle plugins directory when no explicit target is given, reducing stale duplicate installs.
- Broadened test coverage around plugin-backed context, open, and live tag operations.

## 0.11.0
- Added bridge health summaries that expose heartbeat age, queue depth, writability, and plugin-version mismatch information through `bridge status`.
- Added `bridge doctor` and `bridge cleanup` so the external CLI can diagnose stale plugin installs and prune old bridge state without touching the plugin code.
- Hardened bridge response and status-file reads so transient partial JSON no longer fails immediately while the plugin is still writing.
- Tightened bridge timeout guidance so failed rename or move requests explain whether the plugin is missing, stale, or simply waiting on Eagle to restart.

## 0.10.0
- Added persistent `config` commands for shared CLI defaults such as report format, export format, shell completion, and watch state path.
- Added `report dashboard` for combined library, item, tag, folder, and trend summaries in a single output.
- Applied atomic file writes more broadly across plans, snapshots, manifests, reports, bridge requests, presets, and session/watch state.
- Made config defaults flow into report generation, item export, workflow report steps, shell completion, and watch-based imports.

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
