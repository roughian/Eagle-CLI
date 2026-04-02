# CLI-Anything Eagle Bridge Plugin

This companion plugin runs as a background service inside Eagle and processes
queued bridge requests from `cli-anything-eagle`.

Supported bridge actions:

- `ping`
- `rename_items`
- `move_items`

Shared state directory:

```text
~/.config/cli-anything-eagle/bridge
```

The plugin scans `requests/`, writes results to `responses/`, archives handled
requests in `processed/`, and keeps a heartbeat in `status.json`.

Install from the main CLI project:

```bash
cli-anything-eagle bridge install-plugin
cli-anything-eagle --json bridge status
```

If Eagle is already running, restart Eagle after installing the plugin so the
service bridge can start and begin answering `bridge ping`, `item rename-bulk`,
`item move-bulk`, and `snapshot restore --restore-names/--restore-folders`
requests.
