# CLI-Anything Eagle Bridge Plugin

This companion plugin runs as a background service inside Eagle and processes
queued bridge requests from `cli-anything-eagle`.

Supported bridge actions:

- `ping`
- `get_context`
- `get_selected_item_ids`
- `select_items`
- `open_folder`
- `open_items`
- `rename_tag`
- `merge_tags`
- `rename_items`
- `move_items`

Shared state directory:

```text
~/.config/cli-anything-eagle/bridge
```

The plugin scans `requests/`, writes results to `responses/`, archives handled
requests in `processed/`, keeps a heartbeat in `status.json`, and appends
startup/runtime diagnostics to `plugin.log`.

Install from the main CLI project:

```bash
cli-anything-eagle bridge install-plugin
cli-anything-eagle --json bridge status
cli-anything-eagle --json bridge selected-item-ids
```

The main Python package now bundles this plugin template as installable package
data, so `bridge export-plugin` and `bridge install-plugin` still work from
plain wheel installs.

If Eagle is already running, restart Eagle after installing the plugin so the
service bridge can start and begin answering `bridge ping`, `bridge context`,
`item selected`, `item select`, `item open`, `folder selected`, `folder open`,
`tag rename-live`, `tag merge-live`, `item rename-bulk`, `item move-bulk`,
`bridge open-folder`, `bridge select-items`, and
`snapshot restore --restore-names/--restore-folders` requests.
