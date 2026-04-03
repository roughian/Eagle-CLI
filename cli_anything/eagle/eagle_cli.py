from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click
import yaml

from cli_anything.eagle import __version__
from cli_anything.eagle.core.bridge import (
    BRIDGE_PLUGIN_ID,
    BRIDGE_PLUGIN_NAME,
    DEFAULT_WAIT_SECONDS,
    bridge_health,
    bridge_layout,
    companion_plugin_template_dir,
    default_plugin_dir_candidates,
    ensure_bridge_dirs,
    export_companion_plugin,
    install_companion_plugin,
    installed_plugin_paths,
    load_bridge_status,
    prune_bridge_files,
    write_bridge_request,
    wait_for_bridge_response,
)
from cli_anything.eagle.core.client import DEFAULT_BASE_URL, EagleApiError, EagleClient
from cli_anything.eagle.core.config import (
    config_keys,
    config_path as config_file_path,
    load_config,
    set_config_value,
    unset_config_value,
)
from cli_anything.eagle.core.files import atomic_write_json, atomic_write_text
from cli_anything.eagle.core.state import DEFAULT_STATE_DIR, SessionState
from cli_anything.eagle.core.storage import delete_preset, get_preset, load_presets, save_presets, set_preset
from cli_anything.eagle.utils.folders import (
    FolderRecord,
    find_folder_by_path,
    find_folders_by_name,
    flatten_folders,
    normalize_folder_path,
)
from cli_anything.eagle.utils.library import (
    SmartFolderRecord,
    build_library_summary,
    find_smart_folder_by_path,
    find_smart_folders_by_name,
    flatten_smart_folders,
    smart_folder_rule_rows,
    summarize_smart_folder_rules,
    translate_smart_folder_to_item_filter,
)
from cli_anything.eagle.utils.output import emit, render_folder_tree
from cli_anything.eagle.utils.repl import start_repl


FOLDER_COLORS = ["red", "orange", "green", "yellow", "aqua", "blue", "purple", "pink"]


@dataclass
class AppContext:
    state: SessionState
    config: dict[str, Any]
    json_output: bool
    timeout: float
    base_url: str
    dry_run: bool
    _client: EagleClient | None = None

    @property
    def client(self) -> EagleClient:
        if self._client is None:
            self._client = EagleClient(base_url=self.base_url, timeout=self.timeout)
        return self._client


def pass_app(fn):
    return click.pass_obj(fn)


def item_filter_options(fn):
    options = [
        click.option("--folder-path", "folder_paths", multiple=True, help="Exact folder path filter."),
        click.option("--folder-name", "folder_names", multiple=True, help="Exact folder name filter."),
        click.option("--folder", "folders", multiple=True, help="Repeatable folder ID filter."),
        click.option("--tag", "tags", multiple=True, help="Repeatable tag filter."),
        click.option("--ext", default=None),
        click.option("--keyword", default=None),
        click.option("--order-by", default=None, help="Examples: CREATEDATE, -FILESIZE, NAME, -RESOLUTION."),
        click.option("--offset", type=int, default=0, show_default=True),
        click.option("--limit", type=int, default=20, show_default=True),
    ]
    for option in options:
        fn = option(fn)
    return fn


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="cli-anything-eagle")
@click.option("--base-url", default=None, help="Eagle API base URL.")
@click.option("--timeout", default=None, type=float, help="HTTP timeout in seconds.")
@click.option("--json", "json_output", is_flag=True, help="Emit raw JSON.")
@click.option("--dry-run", is_flag=True, help="Preview write operations without sending them.")
@click.pass_context
def cli(
    ctx: click.Context,
    base_url: str | None,
    timeout: float | None,
    json_output: bool,
    dry_run: bool,
) -> None:
    """CLI-Anything style Eagle harness."""
    state = SessionState.load()
    config = load_config()
    defaults = config.get("defaults", {})
    resolved_base_url = (
        base_url
        or os.environ.get("EAGLE_API_BASE_URL")
        or defaults.get("base_url")
        or state.base_url
        or DEFAULT_BASE_URL
    )
    timeout_value = timeout
    if timeout_value is None and os.environ.get("EAGLE_API_TIMEOUT"):
        timeout_value = float(os.environ["EAGLE_API_TIMEOUT"])
    if timeout_value is None and defaults.get("timeout") is not None:
        timeout_value = float(defaults["timeout"])
    resolved_timeout = timeout_value if timeout_value is not None else (state.timeout or 15.0)

    ctx.obj = AppContext(
        state=state,
        config=defaults,
        json_output=json_output,
        timeout=resolved_timeout,
        base_url=resolved_base_url,
        dry_run=dry_run,
        _client=None,
    )

    if ctx.invoked_subcommand is None:
        base_args: list[str] = []
        if resolved_base_url != DEFAULT_BASE_URL:
            base_args.extend(["--base-url", resolved_base_url])
        if resolved_timeout != 15.0:
            base_args.extend(["--timeout", str(resolved_timeout)])
        if json_output:
            base_args.append("--json")
        if dry_run:
            base_args.append("--dry-run")
        start_repl(cli, base_args)


@cli.command()
@pass_app
def doctor(app: AppContext) -> None:
    """Detect which Eagle API variant is available."""
    detection = app.client.detect()
    payload = {
        "base_url": detection.base_url,
        "root_available": detection.root_available,
        "v1_available": detection.v1_available,
        "v2_available": detection.v2_available,
        "inferred_variant": detection.inferred_variant,
        "details": detection.details,
    }
    _emit_and_remember(app, "doctor", payload)


@cli.group()
def config() -> None:
    """Persistent configuration commands."""


@config.command("path")
@pass_app
def config_path_command(app: AppContext) -> None:
    path = config_file_path()
    _emit_and_remember(
        app,
        "config path",
        {
            "status": "success",
            "data": {
                "path": str(path),
                "exists": path.exists(),
            },
        },
    )


@config.command("show")
@click.option("--key", "config_key", type=click.Choice(config_keys()), default=None)
@pass_app
def config_show(app: AppContext, config_key: str | None) -> None:
    document = load_config()
    defaults = document.get("defaults", {})
    data: dict[str, Any]
    if config_key is None:
        data = {
            "path": str(config_file_path()),
            "version": document.get("version", 1),
            "defaults": defaults,
        }
    else:
        data = {
            "path": str(config_file_path()),
            "key": config_key,
            "value": defaults.get(config_key),
            "is_set": config_key in defaults,
        }
    _emit_and_remember(app, "config show", {"status": "success", "data": data})


@config.command("set")
@click.argument("key", type=click.Choice(config_keys()))
@click.argument("value")
@pass_app
def config_set(app: AppContext, key: str, value: str) -> None:
    try:
        normalized = set_config_value(key, value)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    app.config[key] = normalized
    _emit_and_remember(
        app,
        "config set",
        {
            "status": "success",
            "data": {
                "path": str(config_file_path()),
                "key": key,
                "value": normalized,
            },
        },
    )


@config.command("unset")
@click.argument("key", type=click.Choice(config_keys()))
@pass_app
def config_unset(app: AppContext, key: str) -> None:
    removed = unset_config_value(key)
    app.config.pop(key, None)
    _emit_and_remember(
        app,
        "config unset",
        {
            "status": "success",
            "data": {
                "path": str(config_file_path()),
                "key": key,
                "removed": removed,
            },
        },
    )


@cli.group()
def app() -> None:
    """Application commands."""


@app.command("info")
@pass_app
def app_info(app: AppContext) -> None:
    _emit_and_remember(app, "app info", app.client.app_info())


@cli.group()
def library() -> None:
    """Library commands."""


@library.command("info")
@pass_app
def library_info(app: AppContext) -> None:
    _emit_and_remember(app, "library info", app.client.library_info())


@library.command("history")
@pass_app
def library_history(app: AppContext) -> None:
    _emit_and_remember(app, "library history", app.client.library_history())


@library.command("switch")
@click.argument("library_path", type=click.Path())
@pass_app
def library_switch(app: AppContext, library_path: str) -> None:
    _run_mutation(
        app,
        "library switch",
        endpoint="/api/library/switch",
        payload={"libraryPath": library_path},
        action=lambda: app.client.library_switch(library_path),
    )


@library.command("icon")
@click.argument("library_path", type=click.Path())
@click.option("--download", type=click.Path(dir_okay=False, path_type=Path), help="Save the icon to a file.")
@pass_app
def library_icon(app: AppContext, library_path: str, download: Path | None) -> None:
    if download is not None:
        if app.dry_run:
            _emit_and_remember(
                app,
                "library icon",
                {
                    "status": "dry-run",
                    "data": {
                        "action": "download library icon",
                        "source_url": app.client.library_icon_url(library_path),
                        "saved_to": str(download),
                    },
                },
            )
            return
        saved = app.client.library_icon_download(library_path, str(download))
        _emit_and_remember(app, "library icon", {"status": "success", "data": {"saved_to": saved}})
        return
    _emit_and_remember(app, "library icon", {"status": "success", "data": {"url": app.client.library_icon_url(library_path)}})


@library.command("summary")
@pass_app
def library_summary(app: AppContext) -> None:
    info = _library_info_data(app)
    _emit_and_remember(app, "library summary", {"status": "success", "data": build_library_summary(info)})


@library.command("quick-access")
@pass_app
def library_quick_access(app: AppContext) -> None:
    info = _library_info_data(app)
    entries = info.get("quickAccess") or []
    if app.json_output:
        _emit_and_remember(app, "library quick-access", {"status": "success", "data": entries})
        return
    rows = []
    for index, entry in enumerate(entries):
        if isinstance(entry, dict):
            rows.append(
                {
                    "index": index,
                    "id": entry.get("id", ""),
                    "name": entry.get("name", ""),
                    "type": entry.get("vstype") or entry.get("type", ""),
                    "description": entry.get("description", ""),
                }
            )
        else:
            rows.append({"index": index, "value": entry})
    _emit_and_remember(app, "library quick-access", {"status": "success", "data": rows})


@cli.group("smart-folder")
def smart_folder() -> None:
    """Smart folder inspection commands."""


@smart_folder.command("list")
@click.option("--flat", is_flag=True, help="Show a flattened list with smart-folder paths.")
@pass_app
def smart_folder_list(app: AppContext, flat: bool) -> None:
    info = _library_info_data(app)
    data = info.get("smartFolders") or []
    if flat or not app.json_output:
        rows = [_smart_folder_row(record) for record in _smart_folder_records_from_data(data)]
        _emit_and_remember(app, "smart-folder list", {"status": "success", "data": rows})
        return
    _emit_and_remember(app, "smart-folder list", {"status": "success", "data": data})


@smart_folder.command("tree")
@pass_app
def smart_folder_tree(app: AppContext) -> None:
    data = _library_info_data(app).get("smartFolders") or []
    sanitized = _sanitize_output({"status": "success", "data": data})
    app.state.record("smart-folder tree", sanitized)
    app.state.save()
    if app.json_output:
        emit(sanitized, json_output=True)
        return
    click.echo(render_folder_tree(data))


@smart_folder.command("show")
@click.option("--id", "smart_folder_id", default=None, help="Smart-folder ID.")
@click.option("--name", "smart_folder_name", default=None, help="Exact smart-folder name.")
@click.option("--path", "smart_folder_path", default=None, help="Exact smart-folder path.")
@pass_app
def smart_folder_show(
    app: AppContext,
    smart_folder_id: str | None,
    smart_folder_name: str | None,
    smart_folder_path: str | None,
) -> None:
    record = _resolve_smart_folder_selector(
        app,
        smart_folder_id=smart_folder_id,
        smart_folder_name=smart_folder_name,
        smart_folder_path=smart_folder_path,
        purpose="smart folder",
        required=True,
    )
    _emit_and_remember(
        app,
        "smart-folder show",
        {
            "status": "success",
            "data": {
                **_smart_folder_row(record),
                "raw": record.raw,
            },
        },
    )


@smart_folder.command("rules")
@click.option("--id", "smart_folder_id", default=None, help="Smart-folder ID.")
@click.option("--name", "smart_folder_name", default=None, help="Exact smart-folder name.")
@click.option("--path", "smart_folder_path", default=None, help="Exact smart-folder path.")
@pass_app
def smart_folder_rules(
    app: AppContext,
    smart_folder_id: str | None,
    smart_folder_name: str | None,
    smart_folder_path: str | None,
) -> None:
    if any([smart_folder_id, smart_folder_name, smart_folder_path]):
        record = _resolve_smart_folder_selector(
            app,
            smart_folder_id=smart_folder_id,
            smart_folder_name=smart_folder_name,
            smart_folder_path=smart_folder_path,
            purpose="smart folder",
            required=True,
        )
        records = [record]
    else:
        records = _smart_folder_records(app)
    _emit_and_remember(app, "smart-folder rules", {"status": "success", "data": smart_folder_rule_rows(records)})


@smart_folder.command("audit")
@pass_app
def smart_folder_audit(app: AppContext) -> None:
    records = _smart_folder_records(app)
    _emit_and_remember(app, "smart-folder audit", {"status": "success", "data": summarize_smart_folder_rules(records)})


@smart_folder.command("run")
@click.option("--id", "smart_folder_id", default=None, help="Smart-folder ID.")
@click.option("--name", "smart_folder_name", default=None, help="Exact smart-folder name.")
@click.option("--path", "smart_folder_path", default=None, help="Exact smart-folder path.")
@click.option("--limit", type=int, default=20, show_default=True, help="Page size used for item queries.")
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--allow-partial", is_flag=True, help="Run even if some smart-folder rules cannot be translated.")
@click.option("--save-preset", default=None, help="Save the translated query as an item-list preset.")
@pass_app
def smart_folder_run(
    app: AppContext,
    smart_folder_id: str | None,
    smart_folder_name: str | None,
    smart_folder_path: str | None,
    limit: int,
    offset: int,
    order_by: str | None,
    fetch_all: bool,
    allow_partial: bool,
    save_preset: str | None,
) -> None:
    record = _resolve_smart_folder_selector(
        app,
        smart_folder_id=smart_folder_id,
        smart_folder_name=smart_folder_name,
        smart_folder_path=smart_folder_path,
        purpose="smart folder",
        required=True,
    )
    translation = translate_smart_folder_to_item_filter(record)
    if translation["supported_rule_count"] == 0:
        raise click.ClickException(f"Smart folder '{record.path}' does not contain any runnable item-list rules.")
    if translation["unsupported_rule_count"] and not allow_partial:
        raise click.ClickException(_smart_folder_translation_error(record, translation))
    raw_params = dict(translation["item_filter"])
    raw_params["limit"] = limit
    raw_params["offset"] = offset
    raw_params["order_by"] = order_by
    if save_preset:
        set_preset(save_preset, {"kind": "item-list", "params": raw_params})
    query = _query_items_from_raw_params(app, raw_params, fetch_all=fetch_all)
    _emit_and_remember(
        app,
        "smart-folder run",
        {
            "status": "success",
            "data": {
                "smart_folder": _smart_folder_row(record),
                "translation": translation,
                "query": query["query"],
                "pages": query["pages"],
                "fetched_all": fetch_all,
                "item_count": len(query["items"]),
                "items": query["items"],
                "saved_preset": save_preset,
            },
        },
    )


@cli.group("tag-group")
def tag_group() -> None:
    """Tag-group inspection commands."""


@tag_group.command("list")
@pass_app
def tag_group_list(app: AppContext) -> None:
    groups = _tag_groups(app)
    if app.json_output:
        _emit_and_remember(app, "tag-group list", {"status": "success", "data": groups})
        return
    rows = [
        {
            "id": group.get("id", ""),
            "name": group.get("name", ""),
            "color": group.get("color", ""),
            "tag_count": len(group.get("tags") or []),
            "description": group.get("description", ""),
        }
        for group in groups
    ]
    _emit_and_remember(app, "tag-group list", {"status": "success", "data": rows})


@tag_group.command("show")
@click.option("--id", "group_id", default=None, help="Tag-group ID.")
@click.option("--name", "group_name", default=None, help="Exact tag-group name.")
@pass_app
def tag_group_show(app: AppContext, group_id: str | None, group_name: str | None) -> None:
    group = _resolve_tag_group(app, group_id=group_id, group_name=group_name)
    _emit_and_remember(app, "tag-group show", {"status": "success", "data": group})


@cli.group()
def bridge() -> None:
    """Companion plugin bridge commands."""


@bridge.command("status")
@pass_app
def bridge_status(app: AppContext) -> None:
    _emit_and_remember(app, "bridge status", {"status": "success", "data": _bridge_status_payload()})


@bridge.command("doctor")
@click.option("--timeout", type=float, default=2.0, show_default=True, help="Seconds to wait for a ping response.")
@click.option("--skip-ping", is_flag=True, help="Do not enqueue a ping request; only inspect local bridge state.")
@pass_app
def bridge_doctor(app: AppContext, timeout: float, skip_ping: bool) -> None:
    summary = _bridge_status_payload()
    ping: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, severity: str, message: str, details: Any | None = None) -> None:
        checks.append(
            {
                "name": name,
                "ok": ok,
                "status": "success" if ok else severity,
                "message": message,
                "details": details,
            }
        )

    add_check(
        "template",
        bool(summary.get("template_exists")),
        "error",
        "Companion plugin template is available." if summary.get("template_exists") else "Companion plugin template is missing.",
        summary.get("template_dir"),
    )
    add_check(
        "install",
        bool(summary.get("installed_plugin_paths")),
        "error",
        "Companion plugin is installed." if summary.get("installed_plugin_paths") else "Companion plugin is not installed.",
        summary.get("installed_plugin_paths") or summary.get("default_plugin_dirs"),
    )
    writable = summary.get("writable") or {}
    add_check(
        "state-dirs",
        all(bool(value) for value in writable.values()),
        "error",
        "Bridge state directories are writable." if all(bool(value) for value in writable.values()) else "One or more bridge state directories are not writable.",
        writable,
    )
    if summary.get("status_error"):
        add_check("status-file", False, "warning", "Bridge status file exists but could not be parsed.", summary.get("status_error"))
    elif summary.get("status") is None:
        add_check("status-file", False, "warning", "Bridge status file has not been written yet.", summary.get("status_path"))
    else:
        add_check("status-file", True, "success", "Bridge status file is readable.", summary.get("status_path"))

    health = str(summary.get("health") or "offline")
    heartbeat_age_seconds = summary.get("heartbeat_age_seconds")
    if health == "healthy":
        add_check("heartbeat", True, "success", "Bridge heartbeat is healthy.", heartbeat_age_seconds)
    elif health == "stale":
        add_check("heartbeat", False, "warning", "Bridge heartbeat is stale.", heartbeat_age_seconds)
    elif health == "stuck_queue":
        add_check("heartbeat", False, "warning", "Bridge heartbeat is stale and requests are backing up.", heartbeat_age_seconds)
    elif health == "invalid":
        add_check("heartbeat", False, "warning", "Bridge heartbeat could not be parsed.", summary.get("status_error"))
    else:
        add_check("heartbeat", False, "warning", "Bridge heartbeat is offline.", heartbeat_age_seconds)

    if summary.get("queue_depth", 0) == 0:
        add_check("queue", True, "success", "No pending bridge queue backlog.", {"queue_depth": 0})
    else:
        add_check(
            "queue",
            False,
            "warning",
            "Bridge queue has pending files.",
            {
                "queue_depth": summary.get("queue_depth"),
                "pending_request_count": summary.get("pending_request_count"),
                "pending_response_count": summary.get("pending_response_count"),
            },
        )

    plugin_version = summary.get("plugin_version")
    if plugin_version and plugin_version != __version__:
        add_check(
            "version",
            False,
            "warning",
            "Plugin bridge version does not match the CLI version.",
            {"plugin_version": plugin_version, "cli_version": __version__},
        )
    else:
        add_check(
            "version",
            True,
            "success",
            "Plugin bridge version matches the CLI or is not reported.",
            {"plugin_version": plugin_version, "cli_version": __version__},
        )

    if not skip_ping:
        ping = _bridge_ping_probe(app.base_url, timeout_seconds=timeout)
        add_check(
            "ping",
            ping.get("status") == "success",
            "warning" if summary.get("installed_plugin_paths") else "error",
            "Live bridge ping succeeded." if ping.get("status") == "success" else str(ping.get("error") or ping.get("status")),
            ping,
        )
    else:
        add_check("ping", True, "success", "Skipped live ping check.", None)

    ready = bool(summary.get("installed_plugin_paths")) and health == "healthy" and (skip_ping or ping.get("status") == "success")

    _emit_and_remember(
        app,
        "bridge doctor",
        {
            "status": "error"
            if any(check["status"] == "error" for check in checks)
            else "warning"
            if any(check["status"] == "warning" for check in checks)
            else "success",
            "data": {
                **summary,
                "ping": ping,
                "ready": ready,
                "checks": checks,
                "suggestions": _bridge_suggestions(summary, ping),
            },
        },
    )


@bridge.command("context")
@click.option("--item-limit", type=click.IntRange(1, None), default=20, show_default=True, help="Maximum number of selected items to return.")
@click.option("--timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@pass_app
def bridge_context(app: AppContext, item_limit: int, timeout: float) -> None:
    bridge_result = _bridge_request("get_context", {"item_limit": item_limit}, timeout_seconds=timeout, queue_only=False)
    payload = _bridge_response_data(bridge_result)
    _emit_and_remember(
        app,
        "bridge context",
        {
            "status": "success",
            "data": {
                **bridge_result["data"],
                **payload,
            },
        },
    )


@bridge.command("open-folder")
@click.option("--folder-id", default=None, help="Folder ID.")
@click.option("--folder-name", default=None, help="Exact folder name.")
@click.option("--folder-path", default=None, help="Exact folder path.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def bridge_open_folder(
    app: AppContext,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    target = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="folder",
        required=True,
    )
    if app.dry_run:
        _emit_and_remember(app, "bridge open-folder", {"status": "dry-run", "data": {"folder": _folder_row(target)}})
        return
    bridge_result = _bridge_request(
        "open_folder",
        {"folder_id": target.id},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    _emit_and_remember(
        app,
        "bridge open-folder",
        {
            "status": bridge_result.get("status", "success"),
            "data": {
                "folder": _folder_row(target),
                **bridge_result["data"],
                "response": _bridge_response_data(bridge_result),
            },
        },
    )


@bridge.command("select-items")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to select in Eagle.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def bridge_select_items(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        limit=max(len(resolved_item_ids), 1),
        offset=0,
        order_by=None,
        keyword=None,
        ext=None,
        tags=(),
        folders=(),
        folder_names=(),
        folder_paths=(),
    )
    result = _bridge_select_items_result(
        app,
        command_name="bridge select-items",
        item_ids=[str(item.get("id")) for item in items if str(item.get("id"))],
        bridge_timeout=bridge_timeout,
        queue_only=queue_only,
        extra_data={"matched_count": len(items)},
    )
    _emit_and_remember(app, "bridge select-items", result)


@bridge.command("export-plugin")
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path))
@pass_app
def bridge_export_plugin(app: AppContext, output_dir: Path) -> None:
    exported = export_companion_plugin(output_dir)
    _emit_and_remember(app, "bridge export-plugin", {"status": "success", "data": {"exported_to": str(exported)}})


@bridge.command("install-plugin")
@click.option("--plugin-dir", type=click.Path(file_okay=False, path_type=Path), default=None, help="Target Eagle plugins directory.")
@pass_app
def bridge_install_plugin(app: AppContext, plugin_dir: Path | None) -> None:
    candidates = default_plugin_dir_candidates()
    target_roots = [plugin_dir] if plugin_dir is not None else [candidate for candidate in candidates if candidate.exists()]
    if not target_roots:
        target_roots = [candidates[0]]
    installed_paths = [install_companion_plugin(target_root) for target_root in target_roots]
    _emit_and_remember(
        app,
        "bridge install-plugin",
        {
            "status": "success",
            "data": {
                "installed_to": str(installed_paths[0]),
                "plugin_root": str(target_roots[0]),
                "installed_to_all": [str(path) for path in installed_paths],
                "plugin_id": BRIDGE_PLUGIN_ID,
                "installed_plugin_paths": [str(path) for path in installed_paths],
                "restart_required": True,
            },
        },
    )


@bridge.command("ping")
@click.option("--timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the ping request without waiting for a response.")
@pass_app
def bridge_ping(app: AppContext, timeout: float, queue_only: bool) -> None:
    result = _bridge_request("ping", {"base_url": app.base_url}, timeout_seconds=timeout, queue_only=queue_only)
    _emit_and_remember(app, "bridge ping", result)


@bridge.command("context")
@click.option("--timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--item-limit", type=click.IntRange(1, None), default=20, show_default=True, help="Maximum selected item rows to return from Eagle.")
@click.option("--queue-only", is_flag=True, help="Queue the context request without waiting for a response.")
@pass_app
def bridge_context(app: AppContext, timeout: float, item_limit: int, queue_only: bool) -> None:
    result = _bridge_request("get_context", {"item_limit": item_limit}, timeout_seconds=timeout, queue_only=queue_only)
    if result.get("status") != "success":
        _emit_and_remember(app, "bridge context", result)
        return
    payload = _bridge_response_data(result)
    _emit_and_remember(
        app,
        "bridge context",
        {
            "status": "success",
            "data": {
                "request_id": result["data"]["request_id"],
                **payload,
            },
        },
    )


@bridge.command("open-folder")
@click.option("--folder-id", default=None, help="Open this exact folder ID inside Eagle.")
@click.option("--folder-name", default=None, help="Resolve and open an exact folder name.")
@click.option("--folder-path", default=None, help="Resolve and open an exact folder path.")
@click.option("--timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the folder-open request without waiting for a response.")
@pass_app
def bridge_open_folder(
    app: AppContext,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
    timeout: float,
    queue_only: bool,
) -> None:
    folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="folder",
        required=True,
    )
    result = _bridge_request("open_folder", {"folder_id": folder.id}, timeout_seconds=timeout, queue_only=queue_only)
    if result.get("status") != "success":
        _emit_and_remember(
            app,
            "bridge open-folder",
            {
                "status": result["status"],
                "data": {
                    "folder": _folder_row(folder),
                    **result["data"],
                },
            },
        )
        return
    payload = _bridge_response_data(result)
    _emit_and_remember(
        app,
        "bridge open-folder",
        {
            "status": "success",
            "data": {
                "request_id": result["data"]["request_id"],
                "folder": _folder_row(folder),
                **payload,
            },
        },
    )


@bridge.command("select-items")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to select inside Eagle.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to select more than this many items.")
@click.option("--timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the selection request without waiting for a response.")
@item_filter_options
@pass_app
def bridge_select_items(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    max_items: int | None,
    timeout: float,
    queue_only: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(items, max_items=max_items, require_match=None, save_matches=None)
    selected_ids = [str(item.get("id")) for item in items if str(item.get("id"))]
    if not selected_ids:
        raise click.ClickException("No items matched the requested selection.")
    result = _bridge_request("select_items", {"item_ids": selected_ids}, timeout_seconds=timeout, queue_only=queue_only)
    if result.get("status") != "success":
        _emit_and_remember(
            app,
            "bridge select-items",
            {
                "status": result["status"],
                "data": {
                    "matched_count": matched_count,
                    "sample_ids": selected_ids[:20],
                    **result["data"],
                },
            },
        )
        return
    payload = _bridge_response_data(result)
    _emit_and_remember(
        app,
        "bridge select-items",
        {
            "status": "success",
            "data": {
                "request_id": result["data"]["request_id"],
                "matched_count": matched_count,
                "sample_ids": selected_ids[:20],
                **payload,
            },
        },
    )


@bridge.command("cleanup")
@click.option("--max-age-hours", type=float, default=24.0, show_default=True, help="Only prune files older than this many hours.")
@click.option("--keep-last", type=click.IntRange(0, None), default=20, show_default=True, help="Keep this many newest files per directory.")
@click.option("--requests/--no-requests", "include_requests", default=False, help="Include pending request files.")
@click.option("--responses/--no-responses", "include_responses", default=True, help="Include response files.")
@click.option("--processed/--no-processed", "include_processed", default=True, help="Include processed request archives.")
@pass_app
def bridge_cleanup(
    app: AppContext,
    max_age_hours: float,
    keep_last: int,
    include_requests: bool,
    include_responses: bool,
    include_processed: bool,
) -> None:
    if not any([include_requests, include_responses, include_processed]):
        raise click.ClickException("Select at least one bridge file group to clean up.")
    result = prune_bridge_files(
        max_age_seconds=max_age_hours * 3600.0,
        keep_last=keep_last,
        include_requests=include_requests,
        include_responses=include_responses,
        include_processed=include_processed,
        dry_run=app.dry_run,
    )
    _emit_and_remember(
        app,
        "bridge cleanup",
        {
            "status": "dry-run" if app.dry_run else "success",
            "data": result,
        },
    )


@cli.group()
def preset() -> None:
    """Saved preset commands."""


@preset.command("list")
@pass_app
def preset_list(app: AppContext) -> None:
    data = load_presets()
    rows = []
    for name, preset_data in sorted(data.get("presets", {}).items()):
        params = preset_data.get("params", {})
        selector = preset_data.get("selector", {})
        mutation = preset_data.get("mutation", {})
        folders = params.get("folder_paths", []) or params.get("folder_names", []) or params.get("folders", [])
        if preset_data.get("kind") == "bulk-update":
            folders = selector.get("folder_paths", []) or selector.get("folder_names", []) or selector.get("folders", [])
        rows.append(
            {
                "name": name,
                "kind": preset_data.get("kind", ""),
                "keyword": params.get("keyword", "") or selector.get("keyword", ""),
                "tags": params.get("tags", []) or selector.get("tags", []),
                "folders": folders,
                "mutation": [key for key, value in mutation.items() if value not in (None, [], ())],
            }
        )
    _emit_and_remember(app, "preset list", {"status": "success", "data": rows})


@preset.command("show")
@click.argument("name")
@pass_app
def preset_show(app: AppContext, name: str) -> None:
    preset_data = get_preset(name)
    if preset_data is None:
        raise click.ClickException(f"Unknown preset: {name}")
    _emit_and_remember(app, "preset show", {"status": "success", "data": {"name": name, **preset_data}})


@preset.command("delete")
@click.argument("name")
@pass_app
def preset_delete(app: AppContext, name: str) -> None:
    if not delete_preset(name):
        raise click.ClickException(f"Unknown preset: {name}")
    _emit_and_remember(app, "preset delete", {"status": "success", "data": {"deleted": name}})


@preset.command("export")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.argument("names", nargs=-1)
@pass_app
def preset_export(app: AppContext, output_file: Path, names: tuple[str, ...]) -> None:
    stored = load_presets()
    available = stored.get("presets", {})
    if names:
        missing = [name for name in names if name not in available]
        if missing:
            raise click.ClickException(f"Unknown preset(s): {', '.join(missing)}")
        selected = {name: available[name] for name in names}
    else:
        selected = dict(available)
    document = {
        "kind": "eagle-cli-preset-bundle",
        "version": 1,
        "presets": selected,
    }
    atomic_write_json(output_file, document)
    _emit_and_remember(
        app,
        "preset export",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "preset_count": len(selected),
                "names": sorted(selected.keys()),
            },
        },
    )


@preset.command("import")
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--overwrite", is_flag=True, help="Replace existing presets with the same name.")
@click.option("--prefix", default="", help="Prefix imported preset names.")
@pass_app
def preset_import(app: AppContext, input_file: Path, overwrite: bool, prefix: str) -> None:
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    incoming = _preset_bundle_presets(payload)
    stored = load_presets()
    existing = stored.setdefault("presets", {})
    imported: list[str] = []
    skipped: list[str] = []
    renamed: list[dict[str, str]] = []
    for name, preset_data in sorted(incoming.items()):
        target_name = f"{prefix}{name}" if prefix else name
        if target_name in existing and not overwrite:
            skipped.append(target_name)
            continue
        existing[target_name] = preset_data
        imported.append(target_name)
        if target_name != name:
            renamed.append({"from": name, "to": target_name})
    save_presets(stored)
    _emit_and_remember(
        app,
        "preset import",
        {
            "status": "success",
            "data": {
                "loaded_from": str(input_file),
                "imported": imported,
                "skipped": skipped,
                "renamed": renamed,
                "overwrite": overwrite,
            },
        },
    )


@preset.command("save-item-list")
@click.argument("name")
@item_filter_options
@pass_app
def preset_save_item_list(
    app: AppContext,
    name: str,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    params = _item_filter_payload_from_args(
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    preset_data = {
        "kind": "item-list",
        "params": params,
    }
    set_preset(name, preset_data)
    _emit_and_remember(app, "preset save-item-list", {"status": "success", "data": {"name": name, **preset_data}})


@preset.command("run-item-list")
@click.argument("name")
@pass_app
def preset_run_item_list(app: AppContext, name: str) -> None:
    preset_data = get_preset(name)
    if preset_data is None:
        raise click.ClickException(f"Unknown preset: {name}")
    if preset_data.get("kind") != "item-list":
        raise click.ClickException(f"Preset '{name}' is not an item-list preset.")
    params = _build_item_filters_from_preset(app, preset_data.get("params", {}))
    _emit_and_remember(app, f"preset run-item-list {name}", app.client.item_list(**params))


@preset.command("save-bulk-update")
@click.argument("name")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to update.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--set-tag", "set_tags", multiple=True, help="Replace tags with this exact set.")
@click.option("--add-tag", "add_tags", multiple=True, help="Append tags without removing existing ones.")
@click.option("--annotation", default=None, help="Set annotation on each matched item.")
@click.option("--url", "source_url", default=None, help="Set source URL on each matched item.")
@click.option("--star", type=click.IntRange(0, 5), default=None, help="Set star rating on each matched item.")
@pass_app
def preset_save_bulk_update(
    app: AppContext,
    name: str,
    item_ids: tuple[str, ...],
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    set_tags: tuple[str, ...],
    add_tags: tuple[str, ...],
    annotation: str | None,
    source_url: str | None,
    star: int | None,
) -> None:
    _validate_bulk_update_request(
        item_ids=item_ids,
        item_file=None,
        use_last=False,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
        set_tags=set_tags,
        add_tags=add_tags,
        annotation=annotation,
        source_url=source_url,
        star=star,
    )
    preset_data = {
        "kind": "bulk-update",
        "selector": {
            "item_ids": list(item_ids),
            "fetch_all": fetch_all,
            **_item_filter_payload_from_args(
                limit=limit,
                offset=offset,
                order_by=order_by,
                keyword=keyword,
                ext=ext,
                tags=tags,
                folders=folders,
                folder_names=folder_names,
                folder_paths=folder_paths,
            ),
        },
        "mutation": {
            "set_tags": list(set_tags),
            "add_tags": list(add_tags),
            "annotation": annotation,
            "source_url": source_url,
            "star": star,
        },
    }
    set_preset(name, preset_data)
    _emit_and_remember(app, "preset save-bulk-update", {"status": "success", "data": {"name": name, **preset_data}})


@preset.command("run-bulk-update")
@click.argument("name")
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated operation plan to a JSON file.")
@pass_app
def preset_run_bulk_update(app: AppContext, name: str, save_plan: Path | None) -> None:
    preset_data = get_preset(name)
    if preset_data is None:
        raise click.ClickException(f"Unknown preset: {name}")
    if preset_data.get("kind") != "bulk-update":
        raise click.ClickException(f"Preset '{name}' is not a bulk-update preset.")
    selector = preset_data.get("selector", {})
    mutation = preset_data.get("mutation", {})
    result = _bulk_update_result(
        app,
        item_ids=tuple(selector.get("item_ids") or []),
        item_file=None,
        use_last=False,
        fetch_all=bool(selector.get("fetch_all")),
        limit=selector.get("limit", 200),
        offset=selector.get("offset", 0),
        order_by=selector.get("order_by"),
        keyword=selector.get("keyword"),
        ext=selector.get("ext"),
        tags=tuple(selector.get("tags") or []),
        folders=tuple(selector.get("folders") or []),
        folder_names=tuple(selector.get("folder_names") or []),
        folder_paths=tuple(selector.get("folder_paths") or []),
        set_tags=tuple(mutation.get("set_tags") or []),
        add_tags=tuple(mutation.get("add_tags") or []),
        annotation=mutation.get("annotation"),
        source_url=mutation.get("source_url"),
        star=mutation.get("star"),
        max_items=None,
        require_match=None,
        skip_unchanged=False,
        save_matches=None,
        save_plan=save_plan,
    )
    _emit_and_remember(app, f"preset run-bulk-update {name}", result)


@cli.group()
def snapshot() -> None:
    """Snapshot and rollback commands."""


@snapshot.command("create")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to snapshot.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Capture all matching items by paging with the current limit as page size.")
@item_filter_options
@pass_app
def snapshot_create(
    app: AppContext,
    output_file: Path,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    document = _snapshot_document(
        "snapshot create",
        items,
        context={
            "fetch_all": fetch_all,
            "filters": _item_filter_payload_from_args(
                limit=limit,
                offset=offset,
                order_by=order_by,
                keyword=keyword,
                ext=ext,
                tags=tags,
                folders=folders,
                folder_names=folder_names,
                folder_paths=folder_paths,
            ),
            "item_ids": list(resolved_item_ids),
        },
    )
    _write_snapshot(output_file, document)
    _emit_and_remember(
        app,
        "snapshot create",
        {"status": "success", "data": {**_snapshot_summary(document), "saved_to": str(output_file)}},
    )


@snapshot.command("show")
@click.argument("snapshot_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@pass_app
def snapshot_show(app: AppContext, snapshot_file: Path) -> None:
    document = _load_snapshot(snapshot_file)
    _emit_and_remember(
        app,
        "snapshot show",
        {
            "status": "success",
            "data": {
                **_snapshot_summary(document),
                "snapshot_file": str(snapshot_file),
                "items": document.get("items", [])[:10],
            },
        },
    )


@snapshot.command("diff")
@click.argument("snapshot_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--include-names", is_flag=True, help="Compare snapshot names against the current Eagle state.")
@click.option("--include-folders", is_flag=True, help="Compare snapshot folder assignments against the current Eagle state.")
@click.option("--save-report", type=click.Path(dir_okay=False, path_type=Path), default=None)
@pass_app
def snapshot_diff(
    app: AppContext,
    snapshot_file: Path,
    include_names: bool,
    include_folders: bool,
    save_report: Path | None,
) -> None:
    document = _load_snapshot(snapshot_file)
    report = _build_snapshot_diff_report(
        document,
        app=app,
        include_names=include_names,
        include_folders=include_folders,
    )
    if save_report is not None:
        _write_manifest(save_report, report)
    _emit_and_remember(
        app,
        "snapshot diff",
        {
            "status": "success",
            "data": {
                **report,
                "snapshot_file": str(snapshot_file),
                "saved_report": str(save_report) if save_report is not None else None,
            },
        },
    )


@snapshot.command("restore")
@click.argument("snapshot_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--restore-names", is_flag=True, help="Also restore item names through the bridge plugin.")
@click.option("--restore-folders", is_flag=True, help="Also restore folder assignments through the bridge plugin.")
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to continue if more than this many snapshot items are restorable.")
@click.option("--require-match", type=click.IntRange(1, None), default=None, help="Require at least this many snapshot items to still exist in Eagle.")
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write currently matched items to a file before restoring.")
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated restore plan to a JSON file.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue bridge work without waiting for a response.")
@click.option("--skip-unchanged", is_flag=True, help="Skip unchanged items when rebuilding restore operations.")
@pass_app
def snapshot_restore(
    app: AppContext,
    snapshot_file: Path,
    restore_names: bool,
    restore_folders: bool,
    max_items: int | None,
    require_match: int | None,
    save_matches: Path | None,
    save_plan: Path | None,
    bridge_timeout: float,
    queue_only: bool,
    skip_unchanged: bool,
) -> None:
    document = _load_snapshot(snapshot_file)
    snapshot_items = list(document.get("items") or [])
    item_ids = tuple(str(item.get("id")) for item in snapshot_items if str(item.get("id")))
    current_items = (
        _collect_target_items(
            app,
            item_ids=item_ids,
            limit=len(item_ids) or 1,
            offset=0,
            order_by=None,
            keyword=None,
            ext=None,
            tags=(),
            folders=(),
            folder_names=(),
            folder_paths=(),
        )
        if item_ids
        else []
    )
    matched_count = _apply_item_guardrails(
        current_items,
        max_items=max_items,
        require_match=require_match,
        save_matches=save_matches,
    )
    current_by_id = {str(item.get("id")): item for item in current_items}

    metadata_operations: list[dict[str, Any]] = []
    rename_operations: list[dict[str, Any]] = []
    move_operations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for snapshot_item_data in snapshot_items:
        item_id = str(snapshot_item_data.get("id") or "")
        if not item_id or item_id not in current_by_id:
            skipped.append({"id": item_id, "reason": "missing"})
            continue
        current_item = current_by_id[item_id]
        metadata_payload = {
            "id": item_id,
            "tags": list(snapshot_item_data.get("tags") or []),
            "annotation": snapshot_item_data.get("annotation"),
            "url": snapshot_item_data.get("url"),
        }
        if snapshot_item_data.get("star") is not None:
            metadata_payload["star"] = snapshot_item_data.get("star")
        changed_fields = _changed_item_fields(current_item, metadata_payload)
        if changed_fields or not skip_unchanged:
            metadata_operations.append(
                {
                    "method": "POST",
                    "endpoint": "/api/item/update",
                    "payload": metadata_payload,
                    "changed_fields": changed_fields,
                    "item": {"id": item_id, "name": current_item.get("name")},
                }
            )
        else:
            skipped.append({"id": item_id, "reason": "metadata-unchanged"})

        if restore_names:
            next_name = str(snapshot_item_data.get("name") or "")
            current_name = str(current_item.get("name") or "")
            if next_name and (next_name != current_name or not skip_unchanged):
                if next_name != current_name:
                    rename_operations.append({"item_id": item_id, "name": current_name, "new_name": next_name})

        if restore_folders:
            next_folders = [str(folder_id) for folder_id in snapshot_item_data.get("folders") or [] if str(folder_id)]
            current_folders = [str(folder_id) for folder_id in current_item.get("folders") or [] if str(folder_id)]
            if next_folders != current_folders:
                move_operations.append(
                    {
                        "item_id": item_id,
                        "name": current_item.get("name"),
                        "current_folders": current_folders,
                        "folder_ids": next_folders,
                    }
                )

    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "snapshot restore",
            _snapshot_restore_operations(metadata_operations, rename_operations, move_operations),
            context={
                "snapshot_file": str(snapshot_file),
                "matched_count": matched_count,
                "snapshot_item_count": len(snapshot_items),
                "restore_names": restore_names,
                "restore_folders": restore_folders,
                "skip_unchanged": skip_unchanged,
            },
        )

    if app.dry_run:
        _emit_and_remember(
            app,
            "snapshot restore",
            {
                "status": "dry-run",
                "data": {
                    "snapshot_file": str(snapshot_file),
                    "matched_count": matched_count,
                    "metadata_operations": metadata_operations,
                    "rename_operations": rename_operations,
                    "move_operations": move_operations,
                    "skipped": skipped,
                    "saved_matches": str(save_matches) if save_matches is not None else None,
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                },
            },
        )
        return

    metadata_results = []
    for operation in metadata_operations:
        payload = operation["payload"]
        response = app.client.item_update(
            payload["id"],
            tags=payload.get("tags"),
            annotation=payload.get("annotation"),
            url=payload.get("url"),
            star=payload.get("star"),
        )
        metadata_results.append({"id": payload["id"], "status": response.get("status", "success")})

    bridge_results: list[dict[str, Any]] = []
    if rename_operations:
        bridge_results.append(
            {
                "action": "rename_items",
                "result": _bridge_request(
                    "rename_items",
                    {"operations": rename_operations},
                    timeout_seconds=bridge_timeout,
                    queue_only=queue_only,
                ),
            }
        )
    if move_operations:
        bridge_results.append(
            {
                "action": "move_items",
                "result": _bridge_request(
                    "move_items",
                    {"operations": move_operations},
                    timeout_seconds=bridge_timeout,
                    queue_only=queue_only,
                ),
            }
        )

    _emit_and_remember(
        app,
        "snapshot restore",
        {
            "status": "success",
            "data": {
                "snapshot_file": str(snapshot_file),
                "matched_count": matched_count,
                "restored_metadata_count": len(metadata_results),
                "rename_operation_count": len(rename_operations),
                "move_operation_count": len(move_operations),
                "skipped": skipped,
                "saved_matches": str(save_matches) if save_matches is not None else None,
                "saved_plan": str(save_plan) if save_plan is not None else None,
                "bridge_results": bridge_results,
            },
        },
    )


@cli.group()
def folder() -> None:
    """Folder commands."""


@folder.command("list")
@click.option("--flat", is_flag=True, help="Show a flattened list with folder paths.")
@pass_app
def folder_list(app: AppContext, flat: bool) -> None:
    data = app.client.folder_list()
    if flat and not app.json_output:
        rows = [_folder_row(record) for record in _folder_records_from_payload(data)]
        _emit_and_remember(app, "folder list", {"status": "success", "data": rows})
        return
    _emit_and_remember(app, "folder list", data)


@folder.command("tree")
@pass_app
def folder_tree(app: AppContext) -> None:
    data = app.client.folder_list()
    sanitized = _sanitize_output(data)
    app.state.record("folder tree", sanitized)
    app.state.save()
    if app.json_output:
        emit(sanitized, json_output=True)
        return
    click.echo(render_folder_tree(sanitized["data"]))


@folder.command("find")
@click.argument("query")
@click.option("--exact", is_flag=True, help="Require an exact folder name match.")
@pass_app
def folder_find(app: AppContext, query: str, exact: bool) -> None:
    records = _folder_records(app)
    matches = find_folders_by_name(records, query, exact=exact)
    _emit_and_remember(app, "folder find", {"status": "success", "data": [_folder_row(item) for item in matches]})


@folder.command("selected")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@pass_app
def folder_selected(app: AppContext, bridge_timeout: float) -> None:
    result = _bridge_request("get_context", {"item_limit": 1}, timeout_seconds=bridge_timeout, queue_only=False)
    payload = _bridge_response_data(result)
    records_by_id = {record.id: record for record in _folder_records(app)}
    rows = []
    for folder in payload.get("selected_folders") or []:
        row = dict(folder)
        record = records_by_id.get(str(folder.get("id") or ""))
        if record is not None:
            row.update(_folder_row(record) or {})
        rows.append(row)
    _emit_and_remember(
        app,
        "folder selected",
        {
            "status": "success",
            "data": {
                "selected_folder_count": payload.get("selected_folder_count", len(rows)),
                "folders": rows,
                "bridge": result["data"],
            },
        },
    )


@folder.command("open")
@click.option("--id", "folder_id", default=None, help="Folder ID.")
@click.option("--name", "folder_name", default=None, help="Exact folder name.")
@click.option("--path", "folder_path", default=None, help="Exact folder path.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def folder_open(
    app: AppContext,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    target = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="folder",
        required=True,
    )
    if app.dry_run:
        _emit_and_remember(
            app,
            "folder open",
            {
                "status": "dry-run",
                "data": {
                    "folder": _folder_row(target),
                    "action": "open_folder",
                },
            },
        )
        return
    bridge_result = _bridge_request(
        "open_folder",
        {"folder_id": target.id},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    payload = _bridge_response_data(bridge_result)
    _emit_and_remember(
        app,
        "folder open",
        {
            "status": bridge_result.get("status", "success"),
            "data": {
                "folder": _folder_row(target),
                "bridge": bridge_result["data"],
                "response": payload,
            },
        },
    )


@folder.command("recent")
@pass_app
def folder_recent(app: AppContext) -> None:
    _emit_and_remember(app, "folder recent", app.client.folder_recent())


@folder.command("create")
@click.argument("folder_name")
@click.option("--parent-id", default=None, help="Parent folder ID.")
@click.option("--parent-name", default=None, help="Exact parent folder name.")
@click.option("--parent-path", default=None, help="Exact parent folder path.")
@pass_app
def folder_create(
    app: AppContext,
    folder_name: str,
    parent_id: str | None,
    parent_name: str | None,
    parent_path: str | None,
) -> None:
    parent = _resolve_folder_selector(
        app,
        folder_id=parent_id,
        folder_name=parent_name,
        folder_path=parent_path,
        purpose="parent folder",
        required=False,
    )
    payload: dict[str, Any] = {"folderName": folder_name}
    if parent is not None:
        payload["parent"] = parent.id
    _run_mutation(
        app,
        "folder create",
        endpoint="/api/folder/create",
        payload=payload,
        action=lambda: app.client.folder_create(folder_name, parent=parent.id if parent else None),
        resolved={"parent": _folder_row(parent) if parent else None},
    )


@folder.command("ensure")
@click.argument("folder_name")
@click.option("--parent-id", default=None, help="Parent folder ID.")
@click.option("--parent-name", default=None, help="Exact parent folder name.")
@click.option("--parent-path", default=None, help="Exact parent folder path.")
@click.option("--description", default=None, help="Leaf folder description to apply.")
@click.option("--color", type=click.Choice(FOLDER_COLORS), default=None, help="Leaf folder color to apply.")
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated operation plan to a JSON file.")
@pass_app
def folder_ensure(
    app: AppContext,
    folder_name: str,
    parent_id: str | None,
    parent_name: str | None,
    parent_path: str | None,
    description: str | None,
    color: str | None,
    save_plan: Path | None,
) -> None:
    parent = _resolve_folder_selector(
        app,
        folder_id=parent_id,
        folder_name=parent_name,
        folder_path=parent_path,
        purpose="parent folder",
        required=False,
    )
    result = _ensure_folder_path(
        app,
        folder_name,
        parent=parent,
        description=description,
        color=color,
    )
    if save_plan is not None:
        _write_plan(
            save_plan,
            _plan_document("folder ensure", result["data"].get("operations", []), context={"folder_name": folder_name}),
        )
    _emit_and_remember(app, "folder ensure", result)


@folder.command("ensure-path")
@click.argument("folder_path")
@click.option("--parent-id", default=None, help="Parent folder ID for the first segment.")
@click.option("--parent-name", default=None, help="Exact parent folder name for the first segment.")
@click.option("--parent-path", default=None, help="Exact parent folder path for the first segment.")
@click.option("--description", default=None, help="Leaf folder description to apply.")
@click.option("--color", type=click.Choice(FOLDER_COLORS), default=None, help="Leaf folder color to apply.")
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated operation plan to a JSON file.")
@pass_app
def folder_ensure_path(
    app: AppContext,
    folder_path: str,
    parent_id: str | None,
    parent_name: str | None,
    parent_path: str | None,
    description: str | None,
    color: str | None,
    save_plan: Path | None,
) -> None:
    parent = _resolve_folder_selector(
        app,
        folder_id=parent_id,
        folder_name=parent_name,
        folder_path=parent_path,
        purpose="parent folder",
        required=False,
    )
    result = _ensure_folder_path(
        app,
        folder_path,
        parent=parent,
        description=description,
        color=color,
    )
    if save_plan is not None:
        _write_plan(
            save_plan,
            _plan_document("folder ensure-path", result["data"].get("operations", []), context={"folder_path": folder_path}),
        )
    _emit_and_remember(app, "folder ensure-path", result)


@folder.command("rename")
@click.argument("folder_id")
@click.argument("new_name")
@pass_app
def folder_rename(app: AppContext, folder_id: str, new_name: str) -> None:
    _run_mutation(
        app,
        "folder rename",
        endpoint="/api/folder/rename",
        payload={"folderId": folder_id, "newName": new_name},
        action=lambda: app.client.folder_rename(folder_id, new_name),
    )


@folder.command("update")
@click.argument("folder_id")
@click.option("--name", "new_name", help="New folder name.")
@click.option("--description", "new_description", help="New folder description.")
@click.option("--color", "new_color", type=click.Choice(FOLDER_COLORS), help="New folder color.")
@pass_app
def folder_update(
    app: AppContext,
    folder_id: str,
    new_name: str | None,
    new_description: str | None,
    new_color: str | None,
) -> None:
    payload: dict[str, Any] = {"folderId": folder_id}
    if new_name is not None:
        payload["newName"] = new_name
    if new_description is not None:
        payload["newDescription"] = new_description
    if new_color is not None:
        payload["newColor"] = new_color
    _run_mutation(
        app,
        "folder update",
        endpoint="/api/folder/update",
        payload=payload,
        action=lambda: app.client.folder_update(
            folder_id,
            new_name=new_name,
            new_description=new_description,
            new_color=new_color,
        ),
    )


@cli.group()
def item() -> None:
    """Item commands."""


@item.command("list")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@item_filter_options
@pass_app
def item_list(
    app: AppContext,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    query = _query_items(
        app,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    _emit_and_remember(app, "item list", {"status": "success", "data": query["items"]})


@item.command("selected")
@click.option("--item-limit", type=click.IntRange(1, None), default=20, show_default=True, help="Maximum selected item rows to return from Eagle.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@pass_app
def item_selected(app: AppContext, item_limit: int, bridge_timeout: float) -> None:
    result = _bridge_request("get_context", {"item_limit": item_limit}, timeout_seconds=bridge_timeout, queue_only=False)
    payload = _bridge_response_data(result)
    _emit_and_remember(
        app,
        "item selected",
        {
            "status": "success",
            "data": {
                "selected_item_count": payload.get("selected_item_count", len(payload.get("selected_items") or [])),
                "truncated_items": payload.get("truncated_items", False),
                "items": payload.get("selected_items") or [],
                "bridge": result["data"],
            },
        },
    )


@item.command("select")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to select in Eagle.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to continue if more than this many items match.")
@click.option("--require-match", type=click.IntRange(1, None), default=None, help="Require at least this many matched items.")
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write matched items to a file before selecting them.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@item_filter_options
@pass_app
def item_select(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    max_items: int | None,
    require_match: int | None,
    save_matches: Path | None,
    bridge_timeout: float,
    queue_only: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(items, max_items=max_items, require_match=require_match, save_matches=save_matches)
    result = _bridge_select_items_result(
        app,
        command_name="item select",
        item_ids=[str(item.get("id")) for item in items if str(item.get("id"))],
        bridge_timeout=bridge_timeout,
        queue_only=queue_only,
        extra_data={
            "matched_count": matched_count,
            "saved_matches": str(save_matches) if save_matches is not None else None,
            "selector": _item_selector_context(
                item_ids=resolved_item_ids,
                fetch_all=fetch_all,
                limit=limit,
                offset=offset,
                order_by=order_by,
                keyword=keyword,
                ext=ext,
                tags=tags,
                folders=folders,
                folder_names=folder_names,
                folder_paths=folder_paths,
            ),
        },
    )
    _emit_and_remember(app, "item select", result)


@item.command("open")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to open inside Eagle.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--window", is_flag=True, help="Ask Eagle to open each item in a new window when supported.")
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to continue if more than this many items match.")
@click.option("--require-match", type=click.IntRange(1, None), default=None, help="Require at least this many matched items.")
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write matched items to a file before opening them.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@item_filter_options
@pass_app
def item_open(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    window: bool,
    max_items: int | None,
    require_match: int | None,
    save_matches: Path | None,
    bridge_timeout: float,
    queue_only: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(items, max_items=max_items, require_match=require_match, save_matches=save_matches)
    selected_ids = [str(item.get("id")) for item in items if str(item.get("id"))]
    if not selected_ids:
        raise click.ClickException("No items matched the requested selection.")
    if app.dry_run:
        _emit_and_remember(
            app,
            "item open",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": matched_count,
                    "window": window,
                    "sample_ids": selected_ids[:20],
                    "saved_matches": str(save_matches) if save_matches is not None else None,
                },
            },
        )
        return
    bridge_result = _bridge_request(
        "open_items",
        {"item_ids": selected_ids, "window": window},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    payload = _bridge_response_data(bridge_result)
    _emit_and_remember(
        app,
        "item open",
        {
            "status": bridge_result.get("status", "success"),
            "data": {
                "matched_count": matched_count,
                "window": window,
                "sample_ids": selected_ids[:20],
                "saved_matches": str(save_matches) if save_matches is not None else None,
                "bridge": bridge_result["data"],
                "response": payload,
            },
        },
    )


@item.command("export")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--format", "export_format", type=click.Choice(["auto", "json", "jsonl", "csv"]), default="auto", show_default=True)
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@item_filter_options
@pass_app
def item_export(
    app: AppContext,
    output_file: Path,
    export_format: str,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    query = _query_items(
        app,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_format = _write_items_export(output_file, query["items"], _effective_export_format(app, export_format))
    _emit_and_remember(
        app,
        "item export",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "format": resolved_format,
                "count": len(query["items"]),
                "pages": query["pages"],
                "query": query["query"],
            },
        },
    )


@item.command("stats")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--top", type=click.IntRange(1, None), default=10, show_default=True, help="Maximum number of rows to show for grouped counts.")
@item_filter_options
@pass_app
def item_stats(
    app: AppContext,
    fetch_all: bool,
    top: int,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    query = _query_items(
        app,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    summary = _summarize_items(app, query["items"], top=top)
    summary["pages"] = query["pages"]
    summary["query"] = query["query"]
    summary["fetched_all"] = fetch_all
    _emit_and_remember(app, "item stats", {"status": "success", "data": summary})


@item.command("info")
@click.argument("item_id")
@pass_app
def item_info(app: AppContext, item_id: str) -> None:
    _emit_and_remember(app, "item info", app.client.item_info(item_id))


@item.command("thumbnail")
@click.argument("item_id")
@pass_app
def item_thumbnail(app: AppContext, item_id: str) -> None:
    _emit_and_remember(app, "item thumbnail", app.client.item_thumbnail(item_id))


@item.command("update")
@click.argument("item_id")
@click.option("--tag", "tags", multiple=True, help="Repeatable replacement tag list.")
@click.option("--annotation", default=None)
@click.option("--url", "source_url", default=None)
@click.option("--star", type=click.IntRange(0, 5), default=None)
@pass_app
def item_update(
    app: AppContext,
    item_id: str,
    tags: tuple[str, ...],
    annotation: str | None,
    source_url: str | None,
    star: int | None,
) -> None:
    payload = {"id": item_id}
    if tags:
        payload["tags"] = list(tags)
    if annotation is not None:
        payload["annotation"] = annotation
    if source_url is not None:
        payload["url"] = source_url
    if star is not None:
        payload["star"] = star
    _run_mutation(
        app,
        "item update",
        endpoint="/api/item/update",
        payload=payload,
        action=lambda: app.client.item_update(
            item_id,
            tags=list(tags) if tags else None,
            annotation=annotation,
            url=source_url,
            star=star,
        ),
    )


@item.command("bulk-update")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to update.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--set-tag", "set_tags", multiple=True, help="Replace tags with this exact set.")
@click.option("--add-tag", "add_tags", multiple=True, help="Append tags without removing existing ones.")
@click.option("--annotation", default=None, help="Set annotation on each matched item.")
@click.option("--url", "source_url", default=None, help="Set source URL on each matched item.")
@click.option("--star", type=click.IntRange(0, 5), default=None, help="Set star rating on each matched item.")
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to continue if more than this many items match.")
@click.option("--require-match", type=click.IntRange(1, None), default=None, help="Require at least this many matched items.")
@click.option("--skip-unchanged", is_flag=True, help="Skip items whose payload would not change any tracked fields.")
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write matched items to a file before applying updates.")
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated operation plan to a JSON file.")
@pass_app
def item_bulk_update(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    set_tags: tuple[str, ...],
    add_tags: tuple[str, ...],
    annotation: str | None,
    source_url: str | None,
    star: int | None,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_matches: Path | None,
    save_plan: Path | None,
) -> None:
    result = _bulk_update_result(
        app,
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
        set_tags=set_tags,
        add_tags=add_tags,
        annotation=annotation,
        source_url=source_url,
        star=star,
        max_items=max_items,
        require_match=require_match,
        skip_unchanged=skip_unchanged,
        save_matches=save_matches,
        save_plan=save_plan,
    )
    _emit_and_remember(app, "item bulk-update", result)


@item.command("rename-bulk")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to rename.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--prefix", default="", help="Prefix to prepend to each name.")
@click.option("--suffix", default="", help="Suffix to append to each name.")
@click.option("--replace-from", default=None, help="Replace this exact substring before prefix/suffix are applied.")
@click.option("--replace-to", default="", help="Replacement string for --replace-from.")
@click.option("--regex-from", default=None, help="Apply a regular-expression replacement before prefix/suffix.")
@click.option("--regex-to", default="", help="Replacement string for --regex-from.")
@click.option(
    "--name-template",
    default=None,
    help="Final rename template using {name}, {original}, {ext}, {id}, and {index}.",
)
@click.option("--strip", "strip_names", is_flag=True, help="Trim leading and trailing whitespace before applying prefix/suffix.")
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to continue if more than this many items match.")
@click.option("--require-match", type=click.IntRange(1, None), default=None, help="Require at least this many matched items.")
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-snapshot", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Save a rollback snapshot before renaming.")
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write matched items to a file before applying updates.")
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated rename plan to a JSON file.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def item_rename_bulk(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    prefix: str,
    suffix: str,
    replace_from: str | None,
    replace_to: str,
    regex_from: str | None,
    regex_to: str,
    name_template: str | None,
    strip_names: bool,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_snapshot: Path | None,
    save_matches: Path | None,
    save_plan: Path | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(
        items,
        max_items=max_items,
        require_match=require_match,
        save_matches=save_matches,
    )
    if save_snapshot is not None:
        _write_snapshot(save_snapshot, _snapshot_document("item rename-bulk", items))
    operations, skipped = _build_rename_operations(
        items,
        prefix=prefix,
        suffix=suffix,
        replace_from=replace_from,
        replace_to=replace_to,
        regex_from=regex_from,
        regex_to=regex_to,
        name_template=name_template,
        strip_names=strip_names,
        skip_unchanged=skip_unchanged,
    )
    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "item rename-bulk",
            [_make_bridge_operation("rename_items", {"operations": operations}, description="Apply bulk item renames")],
            context={
                "matched_count": matched_count,
                "operation_count": len(operations),
                "skipped_count": len(skipped),
                "selector": _item_selector_context(
                    item_ids=resolved_item_ids,
                    fetch_all=fetch_all,
                    limit=limit,
                    offset=offset,
                    order_by=order_by,
                    keyword=keyword,
                    ext=ext,
                    tags=tags,
                    folders=folders,
                    folder_names=folder_names,
                    folder_paths=folder_paths,
                ),
            },
        )
    if app.dry_run:
        _emit_and_remember(
            app,
            "item rename-bulk",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": matched_count,
                    "operation_count": len(operations),
                    "operations": operations,
                    "skipped": skipped,
                    "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                    "saved_matches": str(save_matches) if save_matches is not None else None,
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                },
            },
        )
        return
    bridge_result = _bridge_request(
        "rename_items",
        {"operations": operations},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    _emit_and_remember(
        app,
        "item rename-bulk",
        {
            "status": "success",
            "data": {
                "matched_count": matched_count,
                "operation_count": len(operations),
                "operations": operations,
                "skipped": skipped,
                "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                "saved_matches": str(save_matches) if save_matches is not None else None,
                "saved_plan": str(save_plan) if save_plan is not None else None,
                "bridge": bridge_result,
            },
        },
    )


@item.command("move-bulk")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to move.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--target-folder-id", default=None)
@click.option("--target-folder-name", default=None)
@click.option("--target-folder-path", default=None)
@click.option("--ensure-target-path", default=None, help="Create the target folder path before moving items.")
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to continue if more than this many items match.")
@click.option("--require-match", type=click.IntRange(1, None), default=None, help="Require at least this many matched items.")
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-snapshot", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Save a rollback snapshot before moving.")
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write matched items to a file before applying updates.")
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated move plan to a JSON file.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def item_move_bulk(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    target_folder_id: str | None,
    target_folder_name: str | None,
    target_folder_path: str | None,
    ensure_target_path: str | None,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_snapshot: Path | None,
    save_matches: Path | None,
    save_plan: Path | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(
        items,
        max_items=max_items,
        require_match=require_match,
        save_matches=save_matches,
    )
    if save_snapshot is not None:
        _write_snapshot(save_snapshot, _snapshot_document("item move-bulk", items))
    ensure_result, folder = _resolve_move_target(
        app,
        target_folder_id=target_folder_id,
        target_folder_name=target_folder_name,
        target_folder_path=target_folder_path,
        ensure_target_path=ensure_target_path,
    )
    operations, skipped = _build_move_operations(
        items,
        target_folder_id=folder.id if folder is not None else "",
        target_folder_path=folder.path if folder is not None else "",
        skip_unchanged=skip_unchanged,
    )
    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "item move-bulk",
            [_make_bridge_operation("move_items", {"operations": operations}, description="Apply bulk item moves")],
            context={
                "matched_count": matched_count,
                "operation_count": len(operations),
                "skipped_count": len(skipped),
                "target_folder": _folder_row(folder),
                "selector": _item_selector_context(
                    item_ids=resolved_item_ids,
                    fetch_all=fetch_all,
                    limit=limit,
                    offset=offset,
                    order_by=order_by,
                    keyword=keyword,
                    ext=ext,
                    tags=tags,
                    folders=folders,
                    folder_names=folder_names,
                    folder_paths=folder_paths,
                ),
            },
        )
    if app.dry_run:
        _emit_and_remember(
            app,
            "item move-bulk",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": matched_count,
                    "operation_count": len(operations),
                    "target_folder": _folder_row(folder) if folder is not None else None,
                    "ensure_result": ensure_result,
                    "operations": operations,
                    "skipped": skipped,
                    "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                    "saved_matches": str(save_matches) if save_matches is not None else None,
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                },
            },
        )
        return
    bridge_result = _bridge_request(
        "move_items",
        {"operations": operations},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    _emit_and_remember(
        app,
        "item move-bulk",
        {
            "status": "success",
            "data": {
                "matched_count": matched_count,
                "operation_count": len(operations),
                "target_folder": _folder_row(folder) if folder is not None else None,
                "ensure_result": ensure_result,
                "operations": operations,
                "skipped": skipped,
                "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                "saved_matches": str(save_matches) if save_matches is not None else None,
                "saved_plan": str(save_plan) if save_plan is not None else None,
                "bridge": bridge_result,
            },
        },
    )


@item.command("add-path")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--name", default=None, help="Defaults to the file stem.")
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None, help="Exact target folder name.")
@click.option("--folder-path", default=None, help="Exact target folder path.")
@pass_app
def item_add_path(
    app: AppContext,
    path: str,
    name: str | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
) -> None:
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="target folder",
        required=False,
    )
    resolved_name = name or Path(path).stem
    payload = {"path": path, "name": resolved_name}
    if website:
        payload["website"] = website
    if tags:
        payload["tags"] = list(tags)
    if annotation:
        payload["annotation"] = annotation
    if target_folder:
        payload["folderId"] = target_folder.id
    _run_mutation(
        app,
        "item add-path",
        endpoint="/api/item/addFromPath",
        payload=payload,
        action=lambda: app.client.item_add_from_path(
            path,
            name=resolved_name,
            website=website,
            tags=list(tags) if tags else None,
            annotation=annotation,
            folder_id=target_folder.id if target_folder else None,
        ),
        resolved={"folder": _folder_row(target_folder) if target_folder else None},
    )


@item.command("add-paths")
@click.option("--path", "paths", multiple=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None, help="Exact target folder name.")
@click.option("--folder-path", default=None, help="Exact target folder path.")
@pass_app
def item_add_paths(
    app: AppContext,
    paths: tuple[str, ...],
    manifest: str | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
) -> None:
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="target folder",
        required=False,
    )
    items = _load_batch_items_from_paths(paths, manifest, website=website, tags=list(tags), annotation=annotation)
    payload: dict[str, Any] = {"items": items}
    if target_folder:
        payload["folderId"] = target_folder.id
    _run_mutation(
        app,
        "item add-paths",
        endpoint="/api/item/addFromPaths",
        payload=payload,
        action=lambda: app.client.item_add_from_paths(items, folder_id=target_folder.id if target_folder else None),
        resolved={"folder": _folder_row(target_folder) if target_folder else None},
    )


@item.command("add-dir")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--recursive", is_flag=True, help="Walk subdirectories recursively.")
@click.option("--glob", "globs", multiple=True, help="Repeatable glob filter. Defaults to '*'.")
@click.option("--ext", "extensions", multiple=True, help="Repeatable file extension filter, such as png or jpg.")
@click.option("--hidden", "include_hidden", is_flag=True, help="Include dotfiles and files inside hidden directories.")
@click.option("--limit", type=click.IntRange(1, None), default=None, help="Maximum number of files to add.")
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None, help="Exact target folder name.")
@click.option("--folder-path", default=None, help="Exact target folder path.")
@click.option("--save-manifest", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the generated add-path manifest to a JSON file.")
@click.option(
    "--name-template",
    default=None,
    help="Name template using {name}, {stem}, {ext}, {parent}, {relative}, {relative_stem}, and {index}.",
)
@click.option("--tag-from-path", is_flag=True, help="Append directory names from the relative path as tags.")
@click.option("--tag-from-name", is_flag=True, help="Append name-derived tokens as tags.")
@pass_app
def item_add_dir(
    app: AppContext,
    directory: Path,
    recursive: bool,
    globs: tuple[str, ...],
    extensions: tuple[str, ...],
    include_hidden: bool,
    limit: int | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
    save_manifest: Path | None,
    name_template: str | None,
    tag_from_path: bool,
    tag_from_name: bool,
) -> None:
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="target folder",
        required=False,
    )
    files = _collect_files_from_directory(
        directory,
        recursive=recursive,
        globs=globs,
        extensions=extensions,
        include_hidden=include_hidden,
        limit=limit,
    )
    items = _build_add_dir_items(
        directory,
        files,
        website=website,
        tags=tags,
        annotation=annotation,
        name_template=name_template,
        tag_from_path=tag_from_path,
        tag_from_name=tag_from_name,
    )
    if save_manifest is not None:
        _write_manifest(
            save_manifest,
            {
                "kind": "eagle-cli-add-paths-manifest",
                "version": 1,
                "source_directory": str(directory),
                "recursive": recursive,
                "globs": list(globs),
                "extensions": list(extensions),
                "name_template": name_template,
                "tag_from_path": tag_from_path,
                "tag_from_name": tag_from_name,
                "items": items,
            },
        )
    payload: dict[str, Any] = {"items": items}
    if target_folder:
        payload["folderId"] = target_folder.id
    _run_mutation(
        app,
        "item add-dir",
        endpoint="/api/item/addFromPaths",
        payload=payload,
        action=lambda: app.client.item_add_from_paths(items, folder_id=target_folder.id if target_folder else None),
        resolved={
            "folder": _folder_row(target_folder) if target_folder else None,
            "directory": str(directory),
            "file_count": len(items),
            "name_template": name_template,
            "tag_from_path": tag_from_path,
            "tag_from_name": tag_from_name,
            "saved_manifest": str(save_manifest) if save_manifest is not None else None,
        },
    )


@item.command("add-url")
@click.argument("url")
@click.option("--name", default=None, help="Defaults from the URL path.")
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--star", type=click.IntRange(0, 5), default=None)
@click.option("--annotation", default=None)
@click.option("--modification-time", type=int, default=None)
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None, help="Exact target folder name.")
@click.option("--folder-path", default=None, help="Exact target folder path.")
@click.option("--headers-json", default=None, help="JSON object for custom request headers.")
@pass_app
def item_add_url(
    app: AppContext,
    url: str,
    name: str | None,
    website: str | None,
    tags: tuple[str, ...],
    star: int | None,
    annotation: str | None,
    modification_time: int | None,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
    headers_json: str | None,
) -> None:
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="target folder",
        required=False,
    )
    headers = json.loads(headers_json) if headers_json else None
    resolved_name = name or _derive_name_from_url(url)
    payload = {"url": url, "name": resolved_name}
    if website:
        payload["website"] = website
    if tags:
        payload["tags"] = list(tags)
    if star is not None:
        payload["star"] = star
    if annotation:
        payload["annotation"] = annotation
    if modification_time is not None:
        payload["modificationTime"] = modification_time
    if target_folder:
        payload["folderId"] = target_folder.id
    if headers:
        payload["headers"] = headers
    _run_mutation(
        app,
        "item add-url",
        endpoint="/api/item/addFromURL",
        payload=payload,
        action=lambda: app.client.item_add_from_url(
            url,
            name=resolved_name,
            website=website,
            tags=list(tags) if tags else None,
            star=star,
            annotation=annotation,
            modification_time=modification_time,
            folder_id=target_folder.id if target_folder else None,
            headers=headers,
        ),
        resolved={"folder": _folder_row(target_folder) if target_folder else None},
    )


@item.command("add-urls")
@click.option("--url", "urls", multiple=True)
@click.option("--manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None, help="Exact target folder name.")
@click.option("--folder-path", default=None, help="Exact target folder path.")
@pass_app
def item_add_urls(
    app: AppContext,
    urls: tuple[str, ...],
    manifest: str | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
) -> None:
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="target folder",
        required=False,
    )
    items = _load_batch_items_from_urls(urls, manifest, website=website, tags=list(tags), annotation=annotation)
    payload: dict[str, Any] = {"items": items}
    if target_folder:
        payload["folderId"] = target_folder.id
    _run_mutation(
        app,
        "item add-urls",
        endpoint="/api/item/addFromURLs",
        payload=payload,
        action=lambda: app.client.item_add_from_urls(items, folder_id=target_folder.id if target_folder else None),
        resolved={"folder": _folder_row(target_folder) if target_folder else None},
    )


@item.command("add-bookmark")
@click.argument("url")
@click.option("--name", default=None, help="Defaults from the URL path.")
@click.option("--base64-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--tag", "tags", multiple=True)
@click.option("--modification-time", type=int, default=None)
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None, help="Exact target folder name.")
@click.option("--folder-path", default=None, help="Exact target folder path.")
@pass_app
def item_add_bookmark(
    app: AppContext,
    url: str,
    name: str | None,
    base64_file: str | None,
    tags: tuple[str, ...],
    modification_time: int | None,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
) -> None:
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="target folder",
        required=False,
    )
    base64 = Path(base64_file).read_text(encoding="utf-8") if base64_file else None
    resolved_name = name or _derive_name_from_url(url)
    payload = {"url": url, "name": resolved_name}
    if base64:
        payload["base64"] = base64
    if tags:
        payload["tags"] = list(tags)
    if modification_time is not None:
        payload["modificationTime"] = modification_time
    if target_folder:
        payload["folderId"] = target_folder.id
    _run_mutation(
        app,
        "item add-bookmark",
        endpoint="/api/item/addBookmark",
        payload=payload,
        action=lambda: app.client.item_add_bookmark(
            url,
            name=resolved_name,
            base64=base64,
            tags=list(tags) if tags else None,
            modification_time=modification_time,
            folder_id=target_folder.id if target_folder else None,
        ),
        resolved={"folder": _folder_row(target_folder) if target_folder else None},
    )


@item.command("trash")
@click.argument("item_ids", nargs=-1, required=True)
@pass_app
def item_trash(app: AppContext, item_ids: tuple[str, ...]) -> None:
    _run_mutation(
        app,
        "item trash",
        endpoint="/api/item/moveToTrash",
        payload={"itemIds": list(item_ids)},
        action=lambda: app.client.item_move_to_trash(list(item_ids)),
    )


@item.command("refresh-palette")
@click.argument("item_id")
@pass_app
def item_refresh_palette(app: AppContext, item_id: str) -> None:
    _run_mutation(
        app,
        "item refresh-palette",
        endpoint="/api/item/refreshPalette",
        payload={"id": item_id},
        action=lambda: app.client.item_refresh_palette(item_id),
    )


@item.command("refresh-thumbnail")
@click.argument("item_id")
@pass_app
def item_refresh_thumbnail(app: AppContext, item_id: str) -> None:
    _run_mutation(
        app,
        "item refresh-thumbnail",
        endpoint="/api/item/refreshThumbnail",
        payload={"id": item_id},
        action=lambda: app.client.item_refresh_thumbnail(item_id),
    )


@cli.group()
def audit() -> None:
    """Duplicate and cleanup analysis commands."""


@audit.command("duplicates")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to audit.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--mode", "modes", multiple=True, type=click.Choice(["name", "url", "name-size", "name-ext"]), help="Repeatable duplicate strategy.")
@click.option("--top", type=click.IntRange(1, None), default=10, show_default=True)
@click.option("--save-report", type=click.Path(dir_okay=False, path_type=Path), default=None)
@item_filter_options
@pass_app
def audit_duplicates(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    modes: tuple[str, ...],
    top: int,
    save_report: Path | None,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    report = _build_duplicate_report(query["items"], modes=modes or ("name", "url", "name-size"), top=top)
    report["query"] = query["query"]
    report["pages"] = query["pages"]
    if save_report is not None:
        _write_manifest(save_report, report)
    _emit_and_remember(
        app,
        "audit duplicates",
        {
            "status": "success",
            "data": {
                **report,
                "saved_report": str(save_report) if save_report is not None else None,
            },
        },
    )


@audit.command("cleanup")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to audit.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--sample-limit", type=click.IntRange(1, None), default=10, show_default=True)
@click.option("--save-report", type=click.Path(dir_okay=False, path_type=Path), default=None)
@item_filter_options
@pass_app
def audit_cleanup(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    sample_limit: int,
    save_report: Path | None,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    report = _build_cleanup_report(query["items"], sample_limit=sample_limit)
    report["query"] = query["query"]
    report["pages"] = query["pages"]
    if save_report is not None:
        _write_manifest(save_report, report)
    _emit_and_remember(
        app,
        "audit cleanup",
        {
            "status": "success",
            "data": {
                **report,
                "saved_report": str(save_report) if save_report is not None else None,
            },
        },
    )


@audit.command("cleanup-plan")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    type=click.Choice(["untagged", "unfiled", "missing-url", "missing-annotation", "deleted"]),
    help="Repeatable cleanup selector.",
)
@click.option("--action", type=click.Choice(["add-tag", "trash", "move-folder"]), default="add-tag", show_default=True)
@click.option("--review-tag", default="needs-review", show_default=True)
@click.option("--target-folder-id", default=None)
@click.option("--target-folder-name", default=None)
@click.option("--target-folder-path", default=None)
@click.option("--ensure-target-path", default=None)
@click.option("--batch-size", type=click.IntRange(1, None), default=100, show_default=True)
@click.option("--save-report", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@item_filter_options
@pass_app
def audit_cleanup_plan(
    app: AppContext,
    output_file: Path,
    kinds: tuple[str, ...],
    action: str,
    review_tag: str,
    target_folder_id: str | None,
    target_folder_name: str | None,
    target_folder_path: str | None,
    ensure_target_path: str | None,
    batch_size: int,
    save_report: Path | None,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    selected_kinds = kinds or ("untagged", "unfiled", "missing-url")
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    ensure_result = None
    target_folder = None
    if action == "move-folder":
        ensure_result, target_folder = _resolve_move_target(
            app,
            target_folder_id=target_folder_id,
            target_folder_name=target_folder_name,
            target_folder_path=target_folder_path,
            ensure_target_path=ensure_target_path,
        )
    operations, report = _build_cleanup_plan_operations(
        query["items"],
        kinds=selected_kinds,
        action=action,
        review_tag=review_tag,
        target_folder_id=target_folder.id if target_folder is not None else None,
        target_folder_path=target_folder.path if target_folder is not None else None,
        batch_size=batch_size,
    )
    _write_plan(
        output_file,
        _plan_document(
            "audit cleanup-plan",
            operations,
            context={
                "kinds": list(selected_kinds),
                "action": action,
                "review_tag": review_tag,
                "target_folder": _folder_row(target_folder),
                "query": query["query"],
                "pages": query["pages"],
                "ensure_result": ensure_result,
            },
        ),
    )
    cleanup_report = {
        "title": "CLI-Anything Eagle Cleanup Plan",
        **report,
        "kinds": list(selected_kinds),
        "action": action,
        "target_folder": _folder_row(target_folder),
        "ensure_result": ensure_result,
    }
    if save_report is not None:
        _write_report(save_report, cleanup_report, requested_format="auto")
    _emit_and_remember(
        app,
        "audit cleanup-plan",
        {
            "status": "success",
            "data": {
                **cleanup_report,
                "operation_count": len(operations),
                "saved_plan": str(output_file),
                "saved_report": str(save_report) if save_report is not None else None,
            },
        },
    )


@audit.command("dedupe-plan")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect for duplicates.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--mode", type=click.Choice(["name", "url", "name-size", "name-ext"]), default="name-size", show_default=True)
@click.option("--keep", type=click.Choice(["first", "last", "largest", "smallest", "newest", "oldest"]), default="largest", show_default=True)
@click.option("--batch-size", type=click.IntRange(1, None), default=100, show_default=True)
@click.option("--save-report", type=click.Path(dir_okay=False, path_type=Path), default=None)
@item_filter_options
@pass_app
def audit_dedupe_plan(
    app: AppContext,
    output_file: Path,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    mode: str,
    keep: str,
    batch_size: int,
    save_report: Path | None,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    report = _build_dedupe_plan_report(query["items"], mode=mode, keep=keep, batch_size=batch_size)
    report["query"] = query["query"]
    report["pages"] = query["pages"]
    _write_plan(output_file, _plan_document("audit dedupe-plan", report["operations"], context={k: v for k, v in report.items() if k != "operations"}))
    if save_report is not None:
        _write_manifest(save_report, report)
    _emit_and_remember(
        app,
        "audit dedupe-plan",
        {
            "status": "success",
            "data": {
                **report,
                "saved_plan": str(output_file),
                "saved_report": str(save_report) if save_report is not None else None,
            },
        },
    )


@cli.group()
def organize() -> None:
    """Higher-level organization workflows."""


@organize.command("apply")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to organize.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--set-tag", "set_tags", multiple=True)
@click.option("--add-tag", "add_tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--url", "source_url", default=None)
@click.option("--star", type=click.IntRange(0, 5), default=None)
@click.option("--target-folder-id", default=None)
@click.option("--target-folder-name", default=None)
@click.option("--target-folder-path", default=None)
@click.option("--ensure-target-path", default=None)
@click.option("--name-prefix", default="")
@click.option("--name-suffix", default="")
@click.option("--replace-from", default=None)
@click.option("--replace-to", default="")
@click.option("--regex-from", default=None)
@click.option("--regex-to", default="")
@click.option("--name-template", default=None, help="Final rename template using {name}, {original}, {ext}, {id}, and {index}.")
@click.option("--strip", "strip_names", is_flag=True)
@click.option("--max-items", type=click.IntRange(1, None), default=None, help="Refuse to continue if more than this many items match.")
@click.option("--require-match", type=click.IntRange(1, None), default=None, help="Require at least this many matched items.")
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-snapshot", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue bridge work without waiting for Eagle to process it.")
@pass_app
def organize_apply(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    set_tags: tuple[str, ...],
    add_tags: tuple[str, ...],
    annotation: str | None,
    source_url: str | None,
    star: int | None,
    target_folder_id: str | None,
    target_folder_name: str | None,
    target_folder_path: str | None,
    ensure_target_path: str | None,
    name_prefix: str,
    name_suffix: str,
    replace_from: str | None,
    replace_to: str,
    regex_from: str | None,
    regex_to: str,
    name_template: str | None,
    strip_names: bool,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_snapshot: Path | None,
    save_matches: Path | None,
    save_plan: Path | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(
        items,
        max_items=max_items,
        require_match=require_match,
        save_matches=save_matches,
    )
    if save_snapshot is not None:
        _write_snapshot(save_snapshot, _snapshot_document("organize apply", items))

    metadata_requested = any([set_tags, add_tags, annotation is not None, source_url is not None, star is not None])
    rename_requested = any([name_prefix, name_suffix, replace_from is not None, strip_names])
    move_requested = any([target_folder_id, target_folder_name, target_folder_path, ensure_target_path])

    metadata_result = None
    if metadata_requested:
        metadata_result = _bulk_update_result(
            app,
            item_ids=tuple(str(item.get("id")) for item in items if str(item.get("id"))),
            item_file=None,
            use_last=False,
            fetch_all=False,
            limit=len(items) or 1,
            offset=0,
            order_by=None,
            keyword=None,
            ext=None,
            tags=(),
            folders=(),
            folder_names=(),
            folder_paths=(),
            set_tags=set_tags,
            add_tags=add_tags,
            annotation=annotation,
            source_url=source_url,
            star=star,
            max_items=matched_count,
            require_match=0,
            skip_unchanged=skip_unchanged,
            save_matches=None,
            save_plan=None,
        )

    ensure_result = None
    target_folder = None
    move_operations: list[dict[str, Any]] = []
    move_skipped: list[dict[str, Any]] = []
    if move_requested:
        ensure_result, target_folder = _resolve_move_target(
            app,
            target_folder_id=target_folder_id,
            target_folder_name=target_folder_name,
            target_folder_path=target_folder_path,
            ensure_target_path=ensure_target_path,
        )
        move_operations, move_skipped = _build_move_operations(
            items,
            target_folder_id=target_folder.id if target_folder is not None else "",
            target_folder_path=target_folder.path if target_folder is not None else "",
            skip_unchanged=skip_unchanged,
        )

    rename_operations: list[dict[str, Any]] = []
    rename_skipped: list[dict[str, Any]] = []
    if rename_requested:
        rename_operations, rename_skipped = _build_rename_operations(
            items,
            prefix=name_prefix,
            suffix=name_suffix,
            replace_from=replace_from,
            replace_to=replace_to,
            regex_from=regex_from,
            regex_to=regex_to,
            name_template=name_template,
            strip_names=strip_names,
            skip_unchanged=skip_unchanged,
        )

    aggregate_operations = _organize_plan_operations(
        metadata_result=metadata_result,
        rename_operations=rename_operations,
        move_operations=move_operations,
    )
    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "organize apply",
            aggregate_operations,
            context={
                "matched_count": matched_count,
                "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                "target_folder": _folder_row(target_folder),
                "selector": _item_selector_context(
                    item_ids=resolved_item_ids,
                    fetch_all=fetch_all,
                    limit=limit,
                    offset=offset,
                    order_by=order_by,
                    keyword=keyword,
                    ext=ext,
                    tags=tags,
                    folders=folders,
                    folder_names=folder_names,
                    folder_paths=folder_paths,
                ),
            },
        )

    if app.dry_run:
        _emit_and_remember(
            app,
            "organize apply",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": matched_count,
                    "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                    "saved_matches": str(save_matches) if save_matches is not None else None,
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                    "metadata": metadata_result,
                    "target_folder": _folder_row(target_folder) if target_folder is not None else None,
                    "ensure_result": ensure_result,
                    "move_operations": move_operations,
                    "move_skipped": move_skipped,
                    "rename_operations": rename_operations,
                    "rename_skipped": rename_skipped,
                },
            },
        )
        return

    bridge_results: list[dict[str, Any]] = []
    if rename_operations:
        bridge_results.append(
            {
                "action": "rename_items",
                "result": _bridge_request(
                    "rename_items",
                    {"operations": rename_operations},
                    timeout_seconds=bridge_timeout,
                    queue_only=queue_only,
                ),
            }
        )
    if move_operations:
        bridge_results.append(
            {
                "action": "move_items",
                "result": _bridge_request(
                    "move_items",
                    {"operations": move_operations},
                    timeout_seconds=bridge_timeout,
                    queue_only=queue_only,
                ),
            }
        )

    _emit_and_remember(
        app,
        "organize apply",
        {
            "status": "success",
            "data": {
                "matched_count": matched_count,
                "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                "saved_matches": str(save_matches) if save_matches is not None else None,
                "saved_plan": str(save_plan) if save_plan is not None else None,
                "metadata": metadata_result,
                "target_folder": _folder_row(target_folder) if target_folder is not None else None,
                "ensure_result": ensure_result,
                "move_operation_count": len(move_operations),
                "move_skipped": move_skipped,
                "rename_operation_count": len(rename_operations),
                "rename_skipped": rename_skipped,
                "bridge_results": bridge_results,
            },
        },
    )


@cli.group()
def plan() -> None:
    """Operation plan commands."""


@plan.command("show")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@pass_app
def plan_show(app: AppContext, plan_file: Path) -> None:
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    _emit_and_remember(app, "plan show", {"status": "success", "data": data})


@plan.command("stats")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@pass_app
def plan_stats(app: AppContext, plan_file: Path) -> None:
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    operations = _extract_operations_from_document(data)
    _emit_and_remember(app, "plan stats", {"status": "success", "data": _plan_stats(plan_file, data, operations)})


@plan.command("save-last")
@click.argument("plan_file", type=click.Path(dir_okay=False, path_type=Path))
@pass_app
def plan_save_last(app: AppContext, plan_file: Path) -> None:
    operations = _extract_operations_from_document(app.state.last_response)
    if not operations:
        raise click.ClickException("The last command did not produce any reusable operations.")
    document = _plan_document(app.state.last_command or "last-command", operations, context={"source": "session"})
    _write_plan(plan_file, document)
    _emit_and_remember(app, "plan save-last", {"status": "success", "data": {"saved_to": str(plan_file), "operations": len(operations)}})


@plan.command("apply")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue bridge work without waiting for Eagle to process it.")
@click.option("--save-results", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the plan-apply result document to a JSON file.")
@pass_app
def plan_apply(app: AppContext, plan_file: Path, bridge_timeout: float, queue_only: bool, save_results: Path | None) -> None:
    data = _load_data_file(plan_file)
    operations = _extract_operations_from_document(data)
    if not operations:
        raise click.ClickException("No operations found in the plan file.")
    if app.dry_run:
        response = {
            "status": "dry-run",
            "data": {
                "plan_file": str(plan_file),
                "operations": operations,
                "saved_results": str(save_results) if save_results is not None else None,
            },
        }
        if save_results is not None:
            _write_manifest(save_results, response)
        _emit_and_remember(app, "plan apply", response)
        return

    results = []
    for operation in operations:
        if operation.get("kind") == "bridge":
            response = _bridge_request(
                operation["action"],
                operation.get("payload") or {},
                timeout_seconds=bridge_timeout,
                queue_only=queue_only,
            )
            results.append(
                {
                    "kind": "bridge",
                    "action": operation["action"],
                    "status": response.get("status", "success"),
                    "description": operation.get("description"),
                }
            )
        else:
            response = app.client.raw_request(
                operation.get("method", "POST"),
                operation["endpoint"],
                payload=operation.get("payload"),
            )
            results.append(
                {
                    "kind": "http",
                    "endpoint": operation["endpoint"],
                    "method": operation.get("method", "POST"),
                    "status": response.get("status", "success"),
                    "description": operation.get("description"),
                }
            )

    response = {
        "status": "success",
        "data": {
            "plan_file": str(plan_file),
            "applied_count": len(results),
            "results": results,
            "saved_results": str(save_results) if save_results is not None else None,
        },
    }
    if save_results is not None:
        _write_manifest(save_results, response)
    _emit_and_remember(app, "plan apply", response)


@plan.command("merge")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.argument("plan_files", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@pass_app
def plan_merge(app: AppContext, output_file: Path, plan_files: tuple[Path, ...]) -> None:
    if not plan_files:
        raise click.ClickException("Provide at least one source plan file to merge.")
    merged_operations: list[dict[str, Any]] = []
    source_rows = []
    for plan_path in plan_files:
        data = _load_data_file(plan_path)
        operations = _extract_operations_from_document(data)
        merged_operations.extend(operations)
        source_rows.append(
            {
                "path": str(plan_path),
                "command": data.get("command"),
                "operation_count": len(operations),
            }
        )
    document = _plan_document("plan merge", merged_operations, context={"sources": source_rows})
    _write_plan(output_file, document)
    _emit_and_remember(
        app,
        "plan merge",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "source_count": len(plan_files),
                "operation_count": len(merged_operations),
                "sources": source_rows,
            },
        },
    )


@plan.command("split")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--max-operations", type=click.IntRange(1, None), default=100, show_default=True)
@pass_app
def plan_split(app: AppContext, plan_file: Path, output_dir: Path, max_operations: int) -> None:
    data = _load_data_file(plan_file)
    operations = _extract_operations_from_document(data)
    if not operations:
        raise click.ClickException("No operations found in the plan file.")
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for index, chunk in enumerate(_chunked(operations, max_operations), start=1):
        chunk_path = output_dir / f"{plan_file.stem}-{index:03d}.json"
        _write_plan(
            chunk_path,
            _plan_document(
                f"{data.get('command') or 'plan split'} chunk {index}",
                chunk,
                context={
                    "source_plan": str(plan_file),
                    "chunk_index": index,
                    "chunk_count": len(chunk),
                },
            ),
        )
        saved_paths.append(str(chunk_path))
    _emit_and_remember(
        app,
        "plan split",
        {
            "status": "success",
            "data": {
                "plan_file": str(plan_file),
                "output_dir": str(output_dir),
                "chunk_count": len(saved_paths),
                "paths": saved_paths,
            },
        },
    )


@plan.command("filter")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--kind", type=click.Choice(["http", "bridge"]), default=None)
@click.option("--method", default=None)
@click.option("--endpoint", default=None)
@click.option("--action", default=None)
@click.option("--description-contains", default=None)
@pass_app
def plan_filter(
    app: AppContext,
    plan_file: Path,
    output_file: Path,
    kind: str | None,
    method: str | None,
    endpoint: str | None,
    action: str | None,
    description_contains: str | None,
) -> None:
    data = _load_data_file(plan_file)
    operations = _extract_operations_from_document(data)
    filtered = []
    for operation in operations:
        if kind and operation.get("kind", "http") != kind:
            continue
        if method and str(operation.get("method") or "").casefold() != method.casefold():
            continue
        if endpoint and endpoint not in str(operation.get("endpoint") or ""):
            continue
        if action and action not in str(operation.get("action") or ""):
            continue
        if description_contains and description_contains.casefold() not in str(operation.get("description") or "").casefold():
            continue
        filtered.append(operation)
    _write_plan(
        output_file,
        _plan_document(
            "plan filter",
            filtered,
            context={
                "source_plan": str(plan_file),
                "filters": {
                    "kind": kind,
                    "method": method,
                    "endpoint": endpoint,
                    "action": action,
                    "description_contains": description_contains,
                },
            },
        ),
    )
    _emit_and_remember(
        app,
        "plan filter",
        {
            "status": "success",
            "data": {
                "source_plan": str(plan_file),
                "saved_to": str(output_file),
                "operation_count": len(filtered),
            },
        },
    )


@plan.command("explain")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@pass_app
def plan_explain(app: AppContext, plan_file: Path) -> None:
    data = _load_data_file(plan_file)
    operations = _extract_operations_from_document(data)
    rows = []
    for index, operation in enumerate(operations, start=1):
        rows.append(
            {
                "index": index,
                "kind": operation.get("kind", "http"),
                "method": operation.get("method", ""),
                "endpoint": operation.get("endpoint", ""),
                "action": operation.get("action", ""),
                "description": operation.get("description", ""),
            }
        )
    _emit_and_remember(
        app,
        "plan explain",
        {
            "status": "success",
            "data": {
                "plan_file": str(plan_file),
                "command": data.get("command"),
                "rows": rows,
            },
        },
    )


@plan.command("validate")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@pass_app
def plan_validate(app: AppContext, plan_file: Path) -> None:
    data = _load_data_file(plan_file)
    operations = data.get("operations") if isinstance(data, dict) else None
    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("Plan document must be a JSON or YAML object.")
    else:
        if data.get("kind") not in (None, "eagle-cli-plan"):
            errors.append("Plan kind must be 'eagle-cli-plan' when provided.")
        if not isinstance(operations, list):
            errors.append("Plan document must contain an 'operations' array.")
        else:
            for index, operation in enumerate(operations):
                if not isinstance(operation, dict):
                    errors.append(f"Operation {index} must be an object.")
                    continue
                if operation.get("kind") == "bridge":
                    if not operation.get("action"):
                        errors.append(f"Bridge operation {index} is missing 'action'.")
                else:
                    if not operation.get("endpoint"):
                        errors.append(f"HTTP operation {index} is missing 'endpoint'.")
    _emit_and_remember(
        app,
        "plan validate",
        {
            "status": "success",
            "data": {
                "plan_file": str(plan_file),
                "valid": not errors,
                "errors": errors,
                "operation_count": len(_extract_operations_from_document(data)) if isinstance(data, dict) else 0,
            },
        },
    )


@plan.command("rollback-from-results")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.argument("results_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--restore-names/--no-restore-names", default=True, show_default=True)
@click.option("--restore-folders/--no-restore-folders", default=True, show_default=True)
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None)
@pass_app
def plan_rollback_from_results(
    app: AppContext,
    output_file: Path,
    results_file: Path,
    restore_names: bool,
    restore_folders: bool,
    skip_unchanged: bool,
    save_matches: Path | None,
) -> None:
    results_payload = _load_data_file(results_file)
    snapshot_value = _find_saved_snapshot_path(results_payload)
    if snapshot_value is None:
        raise click.ClickException("Could not find any saved_snapshot path in the results document.")
    snapshot_file = Path(snapshot_value).expanduser()
    document = _load_snapshot(snapshot_file)
    snapshot_items = list(document.get("items") or [])
    item_ids = tuple(str(item.get("id")) for item in snapshot_items if str(item.get("id")))
    current_items = (
        _collect_target_items(
            app,
            item_ids=item_ids,
            limit=len(item_ids) or 1,
            offset=0,
            order_by=None,
            keyword=None,
            ext=None,
            tags=(),
            folders=(),
            folder_names=(),
            folder_paths=(),
        )
        if item_ids
        else []
    )
    if save_matches is not None:
        _write_items_export(save_matches, current_items, "auto")
    current_by_id = {str(item.get("id")): item for item in current_items}
    metadata_operations: list[dict[str, Any]] = []
    rename_operations: list[dict[str, Any]] = []
    move_operations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for snapshot_item_data in snapshot_items:
        item_id = str(snapshot_item_data.get("id") or "")
        if not item_id or item_id not in current_by_id:
            skipped.append({"id": item_id, "reason": "missing"})
            continue
        current_item = current_by_id[item_id]
        metadata_payload = {
            "id": item_id,
            "tags": list(snapshot_item_data.get("tags") or []),
            "annotation": snapshot_item_data.get("annotation"),
            "url": snapshot_item_data.get("url"),
        }
        if snapshot_item_data.get("star") is not None:
            metadata_payload["star"] = snapshot_item_data.get("star")
        changed_fields = _changed_item_fields(current_item, metadata_payload)
        if changed_fields or not skip_unchanged:
            metadata_operations.append(
                {
                    "method": "POST",
                    "endpoint": "/api/item/update",
                    "payload": metadata_payload,
                    "changed_fields": changed_fields,
                    "item": {"id": item_id, "name": current_item.get("name")},
                }
            )
        if restore_names:
            next_name = str(snapshot_item_data.get("name") or "")
            current_name = str(current_item.get("name") or "")
            if next_name and next_name != current_name:
                rename_operations.append({"item_id": item_id, "name": current_name, "new_name": next_name})
        if restore_folders:
            next_folders = [str(folder_id) for folder_id in snapshot_item_data.get("folders") or [] if str(folder_id)]
            current_folders = [str(folder_id) for folder_id in current_item.get("folders") or [] if str(folder_id)]
            if next_folders != current_folders:
                move_operations.append(
                    {
                        "item_id": item_id,
                        "name": current_item.get("name"),
                        "current_folders": current_folders,
                        "folder_ids": next_folders,
                    }
                )
    operations = _snapshot_restore_operations(metadata_operations, rename_operations, move_operations)
    _write_plan(
        output_file,
        _plan_document(
            "plan rollback-from-results",
            operations,
            context={
                "results_file": str(results_file),
                "snapshot_file": str(snapshot_file),
                "restore_names": restore_names,
                "restore_folders": restore_folders,
                "skip_unchanged": skip_unchanged,
            },
        ),
    )
    _emit_and_remember(
        app,
        "plan rollback-from-results",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "results_file": str(results_file),
                "snapshot_file": str(snapshot_file),
                "metadata_operation_count": len(metadata_operations),
                "rename_operation_count": len(rename_operations),
                "move_operation_count": len(move_operations),
                "skipped": skipped,
                "saved_matches": str(save_matches) if save_matches is not None else None,
            },
        },
    )


@cli.group()
def tag() -> None:
    """Tag analysis and transformation commands."""


@tag.command("stats")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--top", type=click.IntRange(1, None), default=15, show_default=True)
@item_filter_options
@pass_app
def tag_stats(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    top: int,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    payload = _build_tag_stats(query["items"], top=top)
    payload["query"] = query["query"]
    payload["pages"] = query["pages"]
    _emit_and_remember(app, "tag stats", {"status": "success", "data": payload})


@tag.command("audit")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--top", type=click.IntRange(1, None), default=15, show_default=True)
@item_filter_options
@pass_app
def tag_audit(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    top: int,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    payload = _build_tag_audit(query["items"], top=top)
    payload["query"] = query["query"]
    payload["pages"] = query["pages"]
    _emit_and_remember(app, "tag audit", {"status": "success", "data": payload})


@tag.command("rename-live")
@click.argument("source")
@click.argument("target")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def tag_rename_live(app: AppContext, source: str, target: str, bridge_timeout: float, queue_only: bool) -> None:
    if app.dry_run:
        _emit_and_remember(
            app,
            "tag rename-live",
            {
                "status": "dry-run",
                "data": {
                    "source": source,
                    "target": target,
                    "action": "rename_tag",
                },
            },
        )
        return
    bridge_result = _bridge_request(
        "rename_tag",
        {"source": source, "target": target},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    payload = _bridge_response_data(bridge_result)
    _emit_and_remember(
        app,
        "tag rename-live",
        {
            "status": bridge_result.get("status", "success"),
            "data": {
                "source": source,
                "target": target,
                "bridge": bridge_result["data"],
                "response": payload,
            },
        },
    )


@tag.command("merge-live")
@click.argument("source")
@click.argument("target")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def tag_merge_live(app: AppContext, source: str, target: str, bridge_timeout: float, queue_only: bool) -> None:
    if app.dry_run:
        _emit_and_remember(
            app,
            "tag merge-live",
            {
                "status": "dry-run",
                "data": {
                    "source": source,
                    "target": target,
                    "action": "merge_tags",
                },
            },
        )
        return
    bridge_result = _bridge_request(
        "merge_tags",
        {"source": source, "target": target},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    payload = _bridge_response_data(bridge_result)
    _emit_and_remember(
        app,
        "tag merge-live",
        {
            "status": bridge_result.get("status", "success"),
            "data": {
                "source": source,
                "target": target,
                "bridge": bridge_result["data"],
                "response": payload,
            },
        },
    )


@tag.command("rename")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to update.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--from-tag", required=True)
@click.option("--to-tag", required=True)
@click.option("--max-items", type=click.IntRange(1, None), default=None)
@click.option("--require-match", type=click.IntRange(1, None), default=None)
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None)
@pass_app
def tag_rename(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    from_tag: str,
    to_tag: str,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_matches: Path | None,
    save_plan: Path | None,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(items, max_items=max_items, require_match=require_match, save_matches=save_matches)

    def transform(item: dict[str, Any]) -> list[str]:
        next_tags: list[str] = []
        for raw_tag in item.get("tags") or []:
            value = to_tag if str(raw_tag) == from_tag else str(raw_tag)
            if value and value not in next_tags:
                next_tags.append(value)
        return next_tags

    operations, skipped = _build_item_update_operations(items, skip_unchanged=skip_unchanged, tag_transform=transform)
    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "tag rename",
            operations,
            context={"from_tag": from_tag, "to_tag": to_tag, "matched_count": matched_count},
        )
    if app.dry_run:
        _emit_and_remember(
            app,
            "tag rename",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": matched_count,
                    "operation_count": len(operations),
                    "operations": operations,
                    "skipped": skipped,
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                    "saved_matches": str(save_matches) if save_matches is not None else None,
                },
            },
        )
        return
    results = _execute_operations(app, operations)
    _emit_and_remember(
        app,
        "tag rename",
        {
            "status": "success",
            "data": {
                "matched_count": matched_count,
                "operation_count": len(operations),
                "skipped": skipped,
                "results": results,
                "saved_plan": str(save_plan) if save_plan is not None else None,
                "saved_matches": str(save_matches) if save_matches is not None else None,
            },
        },
    )


@tag.command("normalize")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to update.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--lowercase", is_flag=True)
@click.option("--trim", is_flag=True)
@click.option("--collapse-spaces", is_flag=True)
@click.option("--max-items", type=click.IntRange(1, None), default=None)
@click.option("--require-match", type=click.IntRange(1, None), default=None)
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None)
@pass_app
def tag_normalize(
    app: AppContext,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    lowercase: bool,
    trim: bool,
    collapse_spaces: bool,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_matches: Path | None,
    save_plan: Path | None,
) -> None:
    if not any([lowercase, trim, collapse_spaces]):
        raise click.ClickException("Provide at least one normalization flag such as --lowercase, --trim, or --collapse-spaces.")
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(items, max_items=max_items, require_match=require_match, save_matches=save_matches)

    def transform(item: dict[str, Any]) -> list[str]:
        next_tags: list[str] = []
        for raw_tag in item.get("tags") or []:
            value = _normalize_tag_value(str(raw_tag), lowercase=lowercase, trim=trim, collapse_spaces=collapse_spaces)
            if value and value not in next_tags:
                next_tags.append(value)
        return next_tags

    operations, skipped = _build_item_update_operations(items, skip_unchanged=skip_unchanged, tag_transform=transform)
    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "tag normalize",
            operations,
            context={
                "matched_count": matched_count,
                "lowercase": lowercase,
                "trim": trim,
                "collapse_spaces": collapse_spaces,
            },
        )
    if app.dry_run:
        _emit_and_remember(
            app,
            "tag normalize",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": matched_count,
                    "operation_count": len(operations),
                    "operations": operations,
                    "skipped": skipped,
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                },
            },
        )
        return
    results = _execute_operations(app, operations)
    _emit_and_remember(
        app,
        "tag normalize",
        {
            "status": "success",
            "data": {
                "matched_count": matched_count,
                "operation_count": len(operations),
                "skipped": skipped,
                "results": results,
                "saved_plan": str(save_plan) if save_plan is not None else None,
            },
        },
    )


@tag.command("alias-map-apply")
@click.argument("alias_map_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to update.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None)
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Filter by existing tags.")
@click.option("--folder", "folders", multiple=True, help="Filter by folder IDs.")
@click.option("--folder-name", "folder_names", multiple=True, help="Filter by exact folder names.")
@click.option("--folder-path", "folder_paths", multiple=True, help="Filter by exact folder paths.")
@click.option("--lowercase", is_flag=True)
@click.option("--trim", is_flag=True)
@click.option("--collapse-spaces", is_flag=True)
@click.option("--max-items", type=click.IntRange(1, None), default=None)
@click.option("--require-match", type=click.IntRange(1, None), default=None)
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-matches", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None)
@pass_app
def tag_alias_map_apply(
    app: AppContext,
    alias_map_file: Path,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    lowercase: bool,
    trim: bool,
    collapse_spaces: bool,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_matches: Path | None,
    save_plan: Path | None,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(items, max_items=max_items, require_match=require_match, save_matches=save_matches)
    alias_map = _load_alias_map(alias_map_file)
    transform = _tag_transform_from_alias_map(
        alias_map,
        lowercase=lowercase,
        trim=trim,
        collapse_spaces=collapse_spaces,
    )
    operations, skipped = _build_item_update_operations(items, skip_unchanged=skip_unchanged, tag_transform=transform)
    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "tag alias-map-apply",
            operations,
            context={
                "matched_count": matched_count,
                "alias_map_file": str(alias_map_file),
                "alias_count": len(alias_map),
            },
        )
    if app.dry_run:
        _emit_and_remember(
            app,
            "tag alias-map-apply",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": matched_count,
                    "operation_count": len(operations),
                    "operations": operations,
                    "skipped": skipped,
                    "alias_map_file": str(alias_map_file),
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                },
            },
        )
        return
    results = _execute_operations(app, operations)
    _emit_and_remember(
        app,
        "tag alias-map-apply",
        {
            "status": "success",
            "data": {
                "matched_count": matched_count,
                "operation_count": len(operations),
                "skipped": skipped,
                "results": results,
                "alias_map_file": str(alias_map_file),
                "saved_plan": str(save_plan) if save_plan is not None else None,
            },
        },
    )


@cli.group("select")
def select_group() -> None:
    """Saved selection set commands."""


@select_group.command("list")
@pass_app
def select_list(app: AppContext) -> None:
    _emit_and_remember(app, "select list", {"status": "success", "data": _list_selections()})


@select_group.command("save")
@click.argument("name")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to save.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@item_filter_options
@pass_app
def select_save(
    app: AppContext,
    name: str,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    saved_ids = [str(item.get("id")) for item in items if str(item.get("id"))]
    path = _save_selection(
        name,
        saved_ids,
        context={
            "selector": _item_selector_context(
                item_ids=resolved_item_ids,
                fetch_all=fetch_all,
                limit=limit,
                offset=offset,
                order_by=order_by,
                keyword=keyword,
                ext=ext,
                tags=tags,
                folders=folders,
                folder_names=folder_names,
                folder_paths=folder_paths,
            ),
        },
    )
    _emit_and_remember(
        app,
        "select save",
        {
            "status": "success",
            "data": {
                "name": name,
                "saved_to": str(path),
                "item_count": len(saved_ids),
                "sample_ids": saved_ids[:10],
            },
        },
    )


@select_group.command("save-current")
@click.argument("name")
@click.option("--timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--item-limit", type=click.IntRange(1, None), default=200, show_default=True, help="Maximum selected items to fetch from Eagle before saving the selection.")
@pass_app
def select_save_current(app: AppContext, name: str, timeout: float, item_limit: int) -> None:
    result = _bridge_request("get_context", {"item_limit": item_limit}, timeout_seconds=timeout, queue_only=False)
    payload = _bridge_response_data(result)
    selected_items = [item for item in payload.get("selected_items") or [] if isinstance(item, dict)]
    saved_ids = [str(item.get("id")) for item in selected_items if str(item.get("id"))]
    if not saved_ids:
        raise click.ClickException("The Eagle plugin did not report any selected items.")
    path = _save_selection(
        name,
        saved_ids,
        context={
            "source": "bridge-current-selection",
            "request_id": result["data"]["request_id"],
            "selected_item_count": payload.get("selected_item_count"),
            "selected_folder_ids": [str(folder.get("id")) for folder in payload.get("selected_folders") or [] if str(folder.get("id"))],
            "truncated_items": bool(payload.get("truncated_items")),
        },
    )
    _emit_and_remember(
        app,
        "select save-current",
        {
            "status": "success",
            "data": {
                "name": name,
                "saved_to": str(path),
                "item_count": len(saved_ids),
                "selected_item_count": payload.get("selected_item_count", len(saved_ids)),
                "selected_folder_count": payload.get("selected_folder_count", 0),
                "truncated_items": bool(payload.get("truncated_items")),
                "sample_ids": saved_ids[:10],
            },
        },
    )


@select_group.command("show")
@click.argument("name")
@pass_app
def select_show(app: AppContext, name: str) -> None:
    _emit_and_remember(app, "select show", {"status": "success", "data": _load_selection(name)})


@select_group.command("capture")
@click.argument("name")
@click.option("--item-limit", type=click.IntRange(1, None), default=50, show_default=True)
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@pass_app
def select_capture(app: AppContext, name: str, item_limit: int, bridge_timeout: float) -> None:
    _emit_and_remember(app, "select capture", _save_current_selection_result(app, name=name, item_limit=item_limit, bridge_timeout=bridge_timeout))


@select_group.command("save-current")
@click.argument("name")
@click.option("--item-limit", type=click.IntRange(1, None), default=50, show_default=True)
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@pass_app
def select_save_current(app: AppContext, name: str, item_limit: int, bridge_timeout: float) -> None:
    _emit_and_remember(app, "select save-current", _save_current_selection_result(app, name=name, item_limit=item_limit, bridge_timeout=bridge_timeout))


@select_group.command("apply")
@click.argument("name")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def select_apply(app: AppContext, name: str, bridge_timeout: float, queue_only: bool) -> None:
    payload = _load_selection(name)
    item_ids = [str(item_id) for item_id in payload.get("item_ids") or [] if str(item_id)]
    result = _bridge_select_items_result(
        app,
        command_name="select apply",
        item_ids=item_ids,
        bridge_timeout=bridge_timeout,
        queue_only=queue_only,
        extra_data={"name": name},
    )
    _emit_and_remember(app, "select apply", result)


@select_group.command("delete")
@click.argument("name")
@pass_app
def select_delete(app: AppContext, name: str) -> None:
    if not _delete_selection(name):
        raise click.ClickException(f"Unknown selection: {name}")
    _emit_and_remember(app, "select delete", {"status": "success", "data": {"deleted": name}})


@select_group.command("sample")
@click.argument("name")
@click.option("--count", type=click.IntRange(1, None), default=10, show_default=True)
@click.option("--offset", type=click.IntRange(0, None), default=0, show_default=True)
@click.option("--resolve", is_flag=True, help="Resolve the sampled IDs to full Eagle item records.")
@pass_app
def select_sample(app: AppContext, name: str, count: int, offset: int, resolve: bool) -> None:
    payload = _load_selection(name)
    item_ids = [str(item_id) for item_id in payload.get("item_ids") or [] if str(item_id)]
    sample_ids = item_ids[offset : offset + count]
    rows: Any
    if resolve and sample_ids:
        rows = _collect_target_items(
            app,
            item_ids=tuple(sample_ids),
            limit=len(sample_ids),
            offset=0,
            order_by=None,
            keyword=None,
            ext=None,
            tags=(),
            folders=(),
            folder_names=(),
            folder_paths=(),
        )
    else:
        rows = [{"index": offset + index, "id": item_id} for index, item_id in enumerate(sample_ids)]
    _emit_and_remember(
        app,
        "select sample",
        {
            "status": "success",
            "data": {
                "name": name,
                "count": len(sample_ids),
                "offset": offset,
                "resolve": resolve,
                "rows": rows,
            },
        },
    )


@select_group.command("diff")
@click.argument("left")
@click.argument("right")
@pass_app
def select_diff(app: AppContext, left: str, right: str) -> None:
    left_doc = _load_selection(left)
    right_doc = _load_selection(right)
    left_ids = [str(item_id) for item_id in left_doc.get("item_ids") or [] if str(item_id)]
    right_ids = [str(item_id) for item_id in right_doc.get("item_ids") or [] if str(item_id)]
    left_set = set(left_ids)
    right_set = set(right_ids)
    _emit_and_remember(
        app,
        "select diff",
        {
            "status": "success",
            "data": {
                "left": left,
                "right": right,
                "left_only": [item_id for item_id in left_ids if item_id not in right_set],
                "right_only": [item_id for item_id in right_ids if item_id not in left_set],
                "common": [item_id for item_id in left_ids if item_id in right_set],
            },
        },
    )


@cli.group()
def report() -> None:
    """Report generation commands."""


@report.command("library")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--format", "report_format", type=click.Choice(["auto", "json", "md", "html", "csv"]), default="auto", show_default=True)
@pass_app
def report_library(app: AppContext, output_file: Path, report_format: str) -> None:
    info = _library_info_data(app)
    rows = []
    for index, entry in enumerate(info.get("quickAccess") or []):
        if isinstance(entry, dict):
            rows.append(
                {
                    "index": index,
                    "id": entry.get("id", ""),
                    "name": entry.get("name", ""),
                    "type": entry.get("vstype") or entry.get("type", ""),
                    "description": entry.get("description", ""),
                }
            )
    document = {
        "title": "CLI-Anything Eagle Library Report",
        **build_library_summary(info),
        "rows": rows,
    }
    resolved_format = _write_report(output_file, document, requested_format=_effective_report_format(app, report_format))
    _emit_and_remember(
        app,
        "report library",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "format": resolved_format,
                "summary": {key: value for key, value in document.items() if key not in {"title", "rows"}},
            },
        },
    )


@report.command("tags")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--format", "report_format", type=click.Choice(["auto", "json", "md", "html", "csv"]), default="auto", show_default=True)
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--top", type=click.IntRange(1, None), default=20, show_default=True)
@item_filter_options
@pass_app
def report_tags(
    app: AppContext,
    output_file: Path,
    report_format: str,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    top: int,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    stats = _build_tag_stats(query["items"], top=top)
    audit = _build_tag_audit(query["items"], top=top)
    document = {
        "title": "CLI-Anything Eagle Tag Report",
        **stats,
        "audit": audit,
        "query": query["query"],
        "pages": query["pages"],
    }
    resolved_format = _write_report(output_file, document, requested_format=_effective_report_format(app, report_format))
    _emit_and_remember(
        app,
        "report tags",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "format": resolved_format,
                "row_count": len(stats["rows"]),
            },
        },
    )


@report.command("folders")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--format", "report_format", type=click.Choice(["auto", "json", "md", "html", "csv"]), default="auto", show_default=True)
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--top", type=click.IntRange(1, None), default=20, show_default=True)
@item_filter_options
@pass_app
def report_folders(
    app: AppContext,
    output_file: Path,
    report_format: str,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    top: int,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    from collections import Counter

    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    folder_map = {record.id: record.path for record in _folder_records(app)}
    counts: Counter[str] = Counter()
    unfiled_items = 0
    for item in query["items"]:
        item_folders = [str(folder_id) for folder_id in item.get("folders") or [] if str(folder_id)]
        if not item_folders:
            counts["(unfiled)"] += 1
            unfiled_items += 1
            continue
        for folder_id in item_folders:
            counts[folder_map.get(folder_id, folder_id)] += 1
    rows = [{"folder": folder, "count": count} for folder, count in counts.most_common(top)]
    document = {
        "title": "CLI-Anything Eagle Folder Report",
        "total_items": len(query["items"]),
        "unfiled_items": unfiled_items,
        "unique_folder_count": len(counts),
        "rows": rows,
        "query": query["query"],
        "pages": query["pages"],
    }
    resolved_format = _write_report(output_file, document, requested_format=_effective_report_format(app, report_format))
    _emit_and_remember(
        app,
        "report folders",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "format": resolved_format,
                "row_count": len(rows),
            },
        },
    )


@report.command("trend")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--format", "report_format", type=click.Choice(["auto", "json", "md", "html", "csv"]), default="auto", show_default=True)
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--bucket", type=click.Choice(["month", "year"]), default="month", show_default=True)
@click.option("--field", type=click.Choice(["created", "modification"]), default="modification", show_default=True)
@item_filter_options
@pass_app
def report_trend(
    app: AppContext,
    output_file: Path,
    report_format: str,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    bucket: str,
    field: str,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    rows = _trend_rows(query["items"], bucket=bucket, field=field)
    document = {
        "title": "CLI-Anything Eagle Trend Report",
        "bucket": bucket,
        "field": field,
        "item_count": len(query["items"]),
        "rows": rows,
        "query": query["query"],
        "pages": query["pages"],
    }
    resolved_format = _write_report(output_file, document, requested_format=_effective_report_format(app, report_format))
    _emit_and_remember(
        app,
        "report trend",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "format": resolved_format,
                "row_count": len(rows),
            },
        },
    )


@report.command("dashboard")
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--format", "report_format", type=click.Choice(["auto", "json", "md", "html"]), default="auto", show_default=True)
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to inspect.")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Load item IDs from a file.")
@click.option("--last", "use_last", is_flag=True, help="Reuse item IDs from the last item-producing command.")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--top", type=click.IntRange(1, None), default=20, show_default=True)
@click.option("--bucket", type=click.Choice(["month", "year"]), default="month", show_default=True)
@click.option("--field", type=click.Choice(["created", "modification"]), default="modification", show_default=True)
@item_filter_options
@pass_app
def report_dashboard(
    app: AppContext,
    output_file: Path,
    report_format: str,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    top: int,
    bucket: str,
    field: str,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    trend_rows = _trend_rows(query["items"], bucket=bucket, field=field)
    document = {
        "title": "CLI-Anything Eagle Dashboard",
        "generated_at": _utc_now(),
        "library": build_library_summary(_library_info_data(app)),
        "item_summary": _summarize_items(app, query["items"], top=top),
        "tag_stats": _build_tag_stats(query["items"], top=top),
        "folder_stats": _build_folder_stats(app, query["items"], top=top),
        "trend": {
            "bucket": bucket,
            "field": field,
            "rows": trend_rows,
        },
        "query": query["query"],
        "pages": query["pages"],
        "rows": trend_rows,
    }
    resolved_format = _write_report(output_file, document, requested_format=_effective_report_format(app, report_format))
    _emit_and_remember(
        app,
        "report dashboard",
        {
            "status": "success",
            "data": {
                "saved_to": str(output_file),
                "format": resolved_format,
                "item_count": len(query["items"]),
                "top": top,
                "bucket": bucket,
                "field": field,
            },
        },
    )


@cli.group()
def workflow() -> None:
    """Declarative workflow commands."""


@workflow.command("validate")
@click.argument("workflow_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@pass_app
def workflow_validate(app: AppContext, workflow_file: Path) -> None:
    payload = _load_workflow(workflow_file)
    validation = _validate_workflow_document(payload)
    _emit_and_remember(
        app,
        "workflow validate",
        {
            "status": "success",
            "data": {
                "workflow_file": str(workflow_file),
                **validation,
            },
        },
    )


@workflow.command("run")
@click.argument("workflow_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--save-plan", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write combined workflow mutations to a plan file.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue bridge work without waiting for Eagle to process it.")
@pass_app
def workflow_run(app: AppContext, workflow_file: Path, save_plan: Path | None, bridge_timeout: float, queue_only: bool) -> None:
    payload = _load_workflow(workflow_file)
    validation = _validate_workflow_document(payload)
    if not validation["valid"]:
        raise click.ClickException("; ".join(validation["errors"]))
    items, query = _workflow_items(app, payload)
    aggregate_operations: list[dict[str, Any]] = []
    step_results = []
    for index, step in enumerate(payload.get("steps") or [], start=1):
        action = step.get("action")
        step_result: dict[str, Any] = {"index": index, "action": action}
        if action == "snapshot":
            output = Path(step["output"])
            document = _snapshot_document(f"workflow:{workflow_file.name}:step-{index}", items, context={"workflow_file": str(workflow_file)})
            if not app.dry_run:
                _write_snapshot(output, document)
            step_result.update({"output": str(output), "item_count": len(items)})
        elif action == "export-items":
            output = Path(step["output"])
            export_format = _effective_export_format(app, str(step.get("format", "auto")))
            if not app.dry_run:
                resolved_format = _write_items_export(output, items, export_format)
                step_result.update({"output": str(output), "format": resolved_format, "item_count": len(items)})
            else:
                step_result.update({"output": str(output), "format": export_format, "item_count": len(items)})
        elif action == "report-tags":
            output = Path(step["output"])
            top = int(step.get("top", 20))
            requested_format = _effective_report_format(app, str(step.get("format", "auto")))
            document = {
                "title": "CLI-Anything Eagle Tag Report",
                **_build_tag_stats(items, top=top),
                "audit": _build_tag_audit(items, top=top),
            }
            if not app.dry_run:
                step_result.update({"output": str(output), "format": _write_report(output, document, requested_format=requested_format)})
            else:
                step_result.update({"output": str(output), "format": requested_format})
        elif action == "report-folders":
            output = Path(step["output"])
            requested_format = _effective_report_format(app, str(step.get("format", "auto")))
            folder_map = {record.id: record.path for record in _folder_records(app)}
            from collections import Counter

            counts: Counter[str] = Counter()
            for item in items:
                item_folders = [str(folder_id) for folder_id in item.get("folders") or [] if str(folder_id)]
                if not item_folders:
                    counts["(unfiled)"] += 1
                    continue
                for folder_id in item_folders:
                    counts[folder_map.get(folder_id, folder_id)] += 1
            document = {
                "title": "CLI-Anything Eagle Folder Report",
                "rows": [{"folder": folder, "count": count} for folder, count in counts.most_common(int(step.get("top", 20)))],
                "total_items": len(items),
            }
            if not app.dry_run:
                step_result.update({"output": str(output), "format": _write_report(output, document, requested_format=requested_format)})
            else:
                step_result.update({"output": str(output), "format": requested_format})
        elif action == "report-trend":
            output = Path(step["output"])
            requested_format = _effective_report_format(app, str(step.get("format", "auto")))
            document = {
                "title": "CLI-Anything Eagle Trend Report",
                "bucket": step.get("bucket", "month"),
                "field": step.get("field", "modification"),
                "rows": _trend_rows(
                    items,
                    bucket=str(step.get("bucket", "month")),
                    field=str(step.get("field", "modification")),
                ),
            }
            if not app.dry_run:
                step_result.update({"output": str(output), "format": _write_report(output, document, requested_format=requested_format)})
            else:
                step_result.update({"output": str(output), "format": requested_format})
        elif action == "bulk-update":
            operations, skipped = _build_item_update_operations(
                items,
                set_tags=tuple(step.get("set_tags") or []),
                add_tags=tuple(step.get("add_tags") or []),
                annotation=step.get("annotation"),
                source_url=step.get("source_url"),
                star=step.get("star"),
                skip_unchanged=bool(step.get("skip_unchanged")),
            )
            aggregate_operations.extend(operations)
            if app.dry_run:
                _simulate_http_operations(items, operations)
                step_result.update({"operation_count": len(operations), "skipped": skipped})
            else:
                step_result.update({"operation_count": len(operations), "skipped": skipped, "results": _execute_operations(app, operations)})
        elif action == "rename":
            operations, skipped = _build_rename_operations(
                items,
                prefix=str(step.get("prefix", "")),
                suffix=str(step.get("suffix", "")),
                replace_from=step.get("replace_from"),
                replace_to=str(step.get("replace_to", "")),
                regex_from=step.get("regex_from"),
                regex_to=step.get("regex_to"),
                name_template=step.get("name_template"),
                strip_names=bool(step.get("strip_names")),
                skip_unchanged=bool(step.get("skip_unchanged")),
            )
            bridge_operations = (
                [_make_bridge_operation("rename_items", {"operations": operations}, description=f"Workflow rename step {index}")]
                if operations
                else []
            )
            aggregate_operations.extend(bridge_operations)
            if app.dry_run:
                _simulate_rename_operations(items, operations)
                step_result.update({"operation_count": len(operations), "skipped": skipped})
            else:
                step_result.update(
                    {
                        "operation_count": len(operations),
                        "skipped": skipped,
                        "results": _execute_operations(
                            app,
                            bridge_operations,
                            bridge_timeout=bridge_timeout,
                            queue_only=queue_only,
                        ),
                    }
                )
        elif action == "move":
            ensure_result, folder = _resolve_move_target(
                app,
                target_folder_id=step.get("target_folder_id"),
                target_folder_name=step.get("target_folder_name"),
                target_folder_path=step.get("target_folder_path"),
                ensure_target_path=step.get("ensure_target_path"),
            )
            operations, skipped = _build_move_operations(
                items,
                target_folder_id=folder.id if folder is not None else "",
                target_folder_path=folder.path if folder is not None else "",
                skip_unchanged=bool(step.get("skip_unchanged")),
            )
            bridge_operations = (
                [_make_bridge_operation("move_items", {"operations": operations}, description=f"Workflow move step {index}")]
                if operations
                else []
            )
            aggregate_operations.extend(bridge_operations)
            if app.dry_run:
                _simulate_move_operations(items, operations)
                step_result.update({"operation_count": len(operations), "skipped": skipped, "target_folder": _folder_row(folder), "ensure_result": ensure_result})
            else:
                step_result.update(
                    {
                        "operation_count": len(operations),
                        "skipped": skipped,
                        "target_folder": _folder_row(folder),
                        "ensure_result": ensure_result,
                        "results": _execute_operations(
                            app,
                            bridge_operations,
                            bridge_timeout=bridge_timeout,
                            queue_only=queue_only,
                        ),
                    }
                )
        else:
            raise click.ClickException(f"Unsupported workflow step action: {action}")
        step_results.append(step_result)
    if save_plan is not None:
        _save_plan_if_requested(
            save_plan,
            "workflow run",
            aggregate_operations,
            context={
                "workflow_file": str(workflow_file),
                "query": query["query"],
                "pages": query["pages"],
            },
        )
    _emit_and_remember(
        app,
        "workflow run",
        {
            "status": "dry-run" if app.dry_run else "success",
            "data": {
                "workflow_file": str(workflow_file),
                "item_count": len(items),
                "steps": step_results,
                "saved_plan": str(save_plan) if save_plan is not None else None,
            },
        },
    )


@cli.group()
def ingest() -> None:
    """Manifest-driven import commands."""


@ingest.command("manifest")
@click.argument("manifest_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None)
@click.option("--folder-path", default=None)
@pass_app
def ingest_manifest(
    app: AppContext,
    manifest_file: Path,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
) -> None:
    payload = _load_data_file(manifest_file)
    if not isinstance(payload, dict):
        raise click.ClickException("Manifest file must be a JSON or YAML object.")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise click.ClickException("Manifest file must contain a non-empty 'items' array.")
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id or payload.get("folder_id"),
        folder_name=folder_name or payload.get("folder_name"),
        folder_path=folder_path or payload.get("folder_path"),
        purpose="target folder",
        required=False,
    )
    request_payload: dict[str, Any] = {"items": items}
    if target_folder is not None:
        request_payload["folderId"] = target_folder.id
    _run_mutation(
        app,
        "ingest manifest",
        endpoint="/api/item/addFromPaths",
        payload=request_payload,
        action=lambda: app.client.item_add_from_paths(items, folder_id=target_folder.id if target_folder else None),
        resolved={
            "manifest_file": str(manifest_file),
            "item_count": len(items),
            "folder": _folder_row(target_folder) if target_folder is not None else None,
        },
    )


@cli.group()
def watch() -> None:
    """Incremental import watch helpers."""


@watch.command("import-dir")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--recursive", is_flag=True, help="Walk subdirectories recursively.")
@click.option("--glob", "globs", multiple=True, help="Repeatable glob filter. Defaults to '*'.")
@click.option("--ext", "extensions", multiple=True, help="Repeatable file extension filter.")
@click.option("--hidden", "include_hidden", is_flag=True, help="Include dotfiles and files inside hidden directories.")
@click.option("--limit", type=click.IntRange(1, None), default=None)
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--name-template", default=None)
@click.option("--tag-from-path", is_flag=True)
@click.option("--tag-from-name", is_flag=True)
@click.option("--folder-id", default=None)
@click.option("--folder-name", default=None)
@click.option("--folder-path", default=None)
@click.option("--state-file", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Override the watch state file location.")
@click.option("--save-manifest", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--reset-state", is_flag=True, help="Ignore the previous watch state and treat all files as new.")
@pass_app
def watch_import_dir(
    app: AppContext,
    directory: Path,
    recursive: bool,
    globs: tuple[str, ...],
    extensions: tuple[str, ...],
    include_hidden: bool,
    limit: int | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    name_template: str | None,
    tag_from_path: bool,
    tag_from_name: bool,
    folder_id: str | None,
    folder_name: str | None,
    folder_path: str | None,
    state_file: Path | None,
    save_manifest: Path | None,
    reset_state: bool,
) -> None:
    state_file = _effective_watch_state_file(app, state_file)
    target_folder = _resolve_folder_selector(
        app,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose="target folder",
        required=False,
    )
    previous_state = {"version": 1, "files": {}} if reset_state else _load_watch_state(state_file)
    files = _collect_files_from_directory(
        directory,
        recursive=recursive,
        globs=globs,
        extensions=extensions,
        include_hidden=include_hidden,
        limit=limit,
    )
    changed_files = []
    next_files: dict[str, Any] = {}
    for path in files:
        signature = _file_signature(path)
        next_files[str(path)] = signature
        if previous_state.get("files", {}).get(str(path)) != signature:
            changed_files.append(path)
    items = _build_add_dir_items(
        directory,
        changed_files,
        website=website,
        tags=tags,
        annotation=annotation,
        name_template=name_template,
        tag_from_path=tag_from_path,
        tag_from_name=tag_from_name,
    )
    if save_manifest is not None:
        _write_manifest(
            save_manifest,
            {
                "kind": "eagle-cli-add-paths-manifest",
                "version": 1,
                "source_directory": str(directory),
                "watch_state_file": str(_watch_state_path(state_file)),
                "items": items,
            },
        )
    request_payload: dict[str, Any] = {"items": items}
    if target_folder is not None:
        request_payload["folderId"] = target_folder.id
    if app.dry_run:
        _emit_and_remember(
            app,
            "watch import-dir",
            {
                "status": "dry-run",
                "data": {
                    "directory": str(directory),
                    "changed_count": len(changed_files),
                    "changed_files": [str(path) for path in changed_files],
                    "items": items,
                    "state_file": str(_watch_state_path(state_file)),
                    "saved_manifest": str(save_manifest) if save_manifest is not None else None,
                },
            },
        )
        return
    response = app.client.item_add_from_paths(items, folder_id=target_folder.id if target_folder else None) if items else {"status": "success", "data": {"itemIds": []}}
    written_state = _save_watch_state(state_file, {"version": 1, "files": next_files, "updated_at": _utc_now()})
    _emit_and_remember(
        app,
        "watch import-dir",
        {
            "status": "success",
            "data": {
                "directory": str(directory),
                "changed_count": len(changed_files),
                "changed_files": [str(path) for path in changed_files],
                "response": response,
                "state_file": str(written_state),
                "saved_manifest": str(save_manifest) if save_manifest is not None else None,
            },
        },
    )


@cli.group()
def completion() -> None:
    """Shell completion helpers."""


@completion.command("script")
@click.option("--shell", "shell_name", type=click.Choice(["bash", "zsh", "fish"]), default="zsh", show_default=True)
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None)
@pass_app
def completion_script(app: AppContext, shell_name: str, output: Path | None) -> None:
    shell_name = _effective_completion_shell(app, shell_name)
    script = _completion_script(shell_name)
    if output is not None:
        atomic_write_text(output, f"{script}\n")
    _emit_and_remember(
        app,
        "completion script",
        {
            "status": "success",
            "data": {
                "shell": shell_name,
                "script": script,
                "saved_to": str(output) if output is not None else None,
            },
        },
    )


@cli.group()
def schema() -> None:
    """Document schema helpers."""


@schema.command("show")
@click.argument("kind", type=click.Choice(["plan", "snapshot", "selection", "workflow", "report"]))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None)
@pass_app
def schema_show(app: AppContext, kind: str, output: Path | None) -> None:
    document = _schema_document(kind)
    if output is not None:
        _write_manifest(output, document)
    _emit_and_remember(
        app,
        "schema show",
        {
            "status": "success",
            "data": {
                "kind": kind,
                "schema": document,
                "saved_to": str(output) if output is not None else None,
            },
        },
    )


@cli.group()
def raw() -> None:
    """Low-level raw API commands."""


@raw.command("request")
@click.argument("method", type=click.Choice(["GET", "POST"], case_sensitive=False))
@click.argument("path")
@click.option("--query", "queries", multiple=True, help="Repeatable key=value query params.")
@click.option("--body-json", default=None, help="Inline JSON body.")
@click.option("--body-file", type=click.Path(exists=True, dir_okay=False), default=None, help="Path to JSON body file.")
@pass_app
def raw_request(
    app: AppContext,
    method: str,
    path: str,
    queries: tuple[str, ...],
    body_json: str | None,
    body_file: str | None,
) -> None:
    params = _parse_kv_pairs(queries)
    payload = _load_payload(body_json=body_json, body_file=body_file)
    if app.dry_run:
        _emit_and_remember(
            app,
            "raw request",
            {
                "status": "dry-run",
                "data": {
                    "method": method,
                    "path": path,
                    "params": params,
                    "payload": payload,
                },
            },
        )
        return
    _emit_and_remember(app, "raw request", app.client.raw_request(method, path, params=params, payload=payload))


def _emit_and_remember(app: AppContext, command_name: str, response: dict[str, Any]) -> None:
    sanitized = _sanitize_output(response)
    app.state.base_url = app.base_url
    app.state.timeout = app.timeout
    app.state.record(command_name, sanitized)
    app.state.save()
    emit(sanitized, json_output=app.json_output)


def _run_mutation(
    app: AppContext,
    command_name: str,
    *,
    endpoint: str,
    payload: dict[str, Any],
    action,
    resolved: dict[str, Any] | None = None,
) -> None:
    if app.dry_run:
        _emit_and_remember(
            app,
            command_name,
            {
                "status": "dry-run",
                "data": {
                    "endpoint": endpoint,
                    "payload": payload,
                    "resolved": resolved,
                },
            },
        )
        return
    _emit_and_remember(app, command_name, action())


def _build_item_filters(
    app: AppContext,
    *,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> dict[str, Any]:
    raw_params = _item_filter_payload_from_args(
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    return _build_item_filters_from_preset(app, raw_params)


def _item_filter_payload_from_args(
    *,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...] | list[str],
    folders: tuple[str, ...] | list[str],
    folder_names: tuple[str, ...] | list[str],
    folder_paths: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    return {
        "limit": limit,
        "offset": offset,
        "order_by": order_by,
        "keyword": keyword,
        "ext": ext,
        "tags": list(tags),
        "folders": list(folders),
        "folder_names": list(folder_names),
        "folder_paths": list(folder_paths),
    }


def _build_item_filters_from_preset(app: AppContext, raw_params: dict[str, Any]) -> dict[str, Any]:
    resolved_folder_ids = _resolve_folder_filters(
        app,
        folder_ids=list(raw_params.get("folders") or []),
        folder_names=list(raw_params.get("folder_names") or []),
        folder_paths=list(raw_params.get("folder_paths") or []),
    )
    return {
        "limit": raw_params.get("limit", 20),
        "offset": raw_params.get("offset", 0),
        "orderBy": raw_params.get("order_by"),
        "keyword": raw_params.get("keyword"),
        "ext": raw_params.get("ext"),
        "tags": ",".join(raw_params.get("tags") or []) if raw_params.get("tags") else None,
        "folders": ",".join(resolved_folder_ids) if resolved_folder_ids else None,
    }


def _query_items(
    app: AppContext,
    *,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> dict[str, Any]:
    raw_params = _item_filter_payload_from_args(
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    return _query_items_from_raw_params(app, raw_params, fetch_all=fetch_all)


def _query_items_from_raw_params(app: AppContext, raw_params: dict[str, Any], *, fetch_all: bool) -> dict[str, Any]:
    params = _build_item_filters_from_preset(app, raw_params)
    if not fetch_all:
        response = app.client.item_list(**params)
        return {
            "items": list(response.get("data") or []),
            "pages": 1,
            "query": params,
        }

    page_size = int(raw_params.get("limit", 20) or 20)
    current_offset = int(raw_params.get("offset", 0) or 0)
    if page_size < 1:
        raise click.ClickException("The item query page size must be at least 1.")

    items: list[dict[str, Any]] = []
    pages = 0
    while True:
        page_params = dict(params)
        page_params["limit"] = page_size
        page_params["offset"] = current_offset
        response = app.client.item_list(**page_params)
        page_items = list(response.get("data") or [])
        items.extend(page_items)
        pages += 1
        if len(page_items) < page_size:
            break
        current_offset += page_size

    return {
        "items": items,
        "pages": pages,
        "query": params,
    }


def _query_or_collect_items(
    app: AppContext,
    *,
    item_ids: tuple[str, ...],
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> dict[str, Any]:
    if item_ids:
        items = _collect_target_items(
            app,
            item_ids=item_ids,
            fetch_all=False,
            limit=len(item_ids) or 1,
            offset=0,
            order_by=None,
            keyword=None,
            ext=None,
            tags=(),
            folders=(),
            folder_names=(),
            folder_paths=(),
        )
        return {
            "items": items,
            "pages": 1,
            "query": {"item_ids": list(item_ids)},
        }
    return _query_items(
        app,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )


def _bulk_update_result(
    app: AppContext,
    *,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    set_tags: tuple[str, ...],
    add_tags: tuple[str, ...],
    annotation: str | None,
    source_url: str | None,
    star: int | None,
    max_items: int | None,
    require_match: int | None,
    skip_unchanged: bool,
    save_matches: Path | None,
    save_plan: Path | None,
) -> dict[str, Any]:
    _validate_bulk_update_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
        set_tags=set_tags,
        add_tags=add_tags,
        annotation=annotation,
        source_url=source_url,
        star=star,
    )
    resolved_item_ids = _resolve_item_selector_ids(app, item_ids=item_ids, item_file=item_file, use_last=use_last)

    source_items = _collect_target_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    matched_count = _apply_item_guardrails(
        source_items,
        max_items=max_items,
        require_match=require_match,
        save_matches=save_matches,
    )

    operations: list[dict[str, Any]] = []
    skipped_unchanged: list[dict[str, Any]] = []
    for item in source_items:
        next_tags = list(set_tags) if set_tags else None
        if add_tags:
            current_tags = list(item.get("tags") or [])
            for tag in add_tags:
                if tag not in current_tags:
                    current_tags.append(tag)
            next_tags = current_tags

        payload: dict[str, Any] = {"id": item["id"]}
        if next_tags is not None:
            payload["tags"] = next_tags
        if annotation is not None:
            payload["annotation"] = annotation
        if source_url is not None:
            payload["url"] = source_url
        if star is not None:
            payload["star"] = star
        changed_fields = _changed_item_fields(item, payload)
        if skip_unchanged and not changed_fields:
            skipped_unchanged.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                }
            )
            continue
        operations.append(
            {
                "method": "POST",
                "item": {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "existing_tags": item.get("tags") or [],
                },
                "endpoint": "/api/item/update",
                "payload": payload,
                "changed_fields": changed_fields,
                "description": f"Update item {item.get('id')} ({item.get('name')})",
            }
        )

    if save_plan is not None:
        _write_plan(
            save_plan,
            _plan_document(
                "item bulk-update",
                operations,
                context={
                    "matched_count": matched_count,
                    "operation_count": len(operations),
                    "skipped_unchanged_count": len(skipped_unchanged),
                    "filters": _item_filter_payload_from_args(
                        limit=limit,
                        offset=offset,
                        order_by=order_by,
                        keyword=keyword,
                        ext=ext,
                        tags=tags,
                        folders=folders,
                        folder_names=folder_names,
                        folder_paths=folder_paths,
                    ),
                    "item_ids": list(resolved_item_ids),
                    "fetch_all": fetch_all,
                },
            ),
        )

    if app.dry_run:
        return {
            "status": "dry-run",
            "data": {
                "matched_count": matched_count,
                "operation_count": len(operations),
                "skipped_unchanged": skipped_unchanged,
                "operations": operations,
                "saved_matches": str(save_matches) if save_matches is not None else None,
                "saved_plan": str(save_plan) if save_plan is not None else None,
            },
        }

    results = []
    for operation in operations:
        payload = operation["payload"]
        response = app.client.item_update(
            payload["id"],
            tags=payload.get("tags"),
            annotation=payload.get("annotation"),
            url=payload.get("url"),
            star=payload.get("star"),
        )
        results.append(
            {
                "id": payload["id"],
                "name": operation["item"]["name"],
                "updated_fields": sorted([key for key in payload.keys() if key != "id"]),
                "response": response.get("status", "success"),
            }
        )

    return {
        "status": "success",
        "data": {
            "matched_count": matched_count,
            "operation_count": len(operations),
            "updated_count": len(results),
            "skipped_unchanged": skipped_unchanged,
            "items": results,
            "operations": operations,
            "saved_matches": str(save_matches) if save_matches is not None else None,
            "saved_plan": str(save_plan) if save_plan is not None else None,
        },
    }


def _validate_bulk_update_request(
    *,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
    fetch_all: bool,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
    set_tags: tuple[str, ...],
    add_tags: tuple[str, ...],
    annotation: str | None,
    source_url: str | None,
    star: int | None,
) -> None:
    if not any([set_tags, add_tags, annotation is not None, source_url is not None, star is not None]):
        raise click.ClickException("Provide at least one mutation field such as --set-tag, --add-tag, --annotation, --url, or --star.")
    _validate_item_selector_request(
        item_ids=item_ids,
        item_file=item_file,
        use_last=use_last,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )


def _changed_item_fields(item: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    if "tags" in payload and list(item.get("tags") or []) != list(payload.get("tags") or []):
        changed.append("tags")
    if "annotation" in payload and str(item.get("annotation") or "") != str(payload.get("annotation") or ""):
        changed.append("annotation")
    if "url" in payload and str(item.get("url") or "") != str(payload.get("url") or ""):
        changed.append("url")
    if "star" in payload and item.get("star") != payload.get("star"):
        changed.append("star")
    return changed


def _validate_item_selector_request(
    *,
    item_ids: tuple[str, ...],
    item_file: Path | None = None,
    use_last: bool = False,
    fetch_all: bool,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    has_direct_selector = bool(item_ids) or item_file is not None or use_last
    if has_direct_selector and any([fetch_all, keyword, ext, tags, folders, folder_names, folder_paths]):
        raise click.ClickException("Use either explicit item selectors (--item-id/--item-file/--last) or filters, not both.")
    if not has_direct_selector and not fetch_all and not any([keyword, ext, tags, folders, folder_names, folder_paths]):
        raise click.ClickException("Provide explicit --item-id values, at least one filter, or --all.")


def _snapshot_document(command_name: str, items: list[dict[str, Any]], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "eagle-cli-snapshot",
        "version": 1,
        "created_at": _utc_now(),
        "command": command_name,
        "context": context or {},
        "items": [_snapshot_item(item) for item in items],
    }


def _snapshot_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "tags": list(item.get("tags") or []),
        "annotation": item.get("annotation"),
        "url": item.get("url"),
        "star": item.get("star"),
        "folders": list(item.get("folders") or []),
        "ext": item.get("ext"),
        "size": item.get("size"),
        "isDeleted": item.get("isDeleted"),
    }


def _write_snapshot(path: Path, document: dict[str, Any]) -> None:
    atomic_write_json(path, document)


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != "eagle-cli-snapshot":
        raise click.ClickException("Snapshot file is not an eagle-cli-snapshot document.")
    return payload


def _snapshot_summary(document: dict[str, Any]) -> dict[str, Any]:
    items = list(document.get("items") or [])
    return {
        "kind": document.get("kind"),
        "version": document.get("version"),
        "created_at": document.get("created_at"),
        "command": document.get("command"),
        "item_count": len(items),
        "sample_ids": [item.get("id") for item in items[:5]],
    }


def _bridge_status_payload() -> dict[str, Any]:
    summary = bridge_health()
    return {
        "plugin_id": BRIDGE_PLUGIN_ID,
        "plugin_name": BRIDGE_PLUGIN_NAME,
        "template_dir": summary["template_dir"],
        "template_exists": summary["template_exists"],
        "state_dir": summary["layout"]["state_dir"],
        "request_dir": summary["layout"]["requests"],
        "response_dir": summary["layout"]["responses"],
        "processed_dir": summary["layout"]["processed"],
        "status_path": summary["status_path"],
        "installed_plugin_paths": summary["installed_plugin_paths"],
        "default_plugin_dirs": summary["default_plugin_dirs"],
        "health": summary["health"],
        "heartbeat_age_seconds": summary["heartbeat_age_seconds"],
        "queue_depth": summary["queue_depth"],
        "pending_request_count": summary["pending_request_count"],
        "pending_response_count": summary["pending_response_count"],
        "processed_count": summary["processed_count"],
        "writable": summary["writable"],
        "status_error": summary["status_error"],
        "plugin_version": summary["plugin_version"],
        "cli_version": __version__,
        "version_mismatch": bool(summary["plugin_version"]) and summary["plugin_version"] != __version__,
        "status": summary["status"],
    }


def _bridge_suggestions(summary: dict[str, Any], ping: dict[str, Any] | None) -> list[str]:
    suggestions: list[str] = []
    if not summary.get("installed_plugin_paths"):
        suggestions.append("Run `bridge install-plugin` to copy the companion plugin into Eagle's plugins folder.")
    elif summary.get("health") != "healthy":
        suggestions.append("Restart Eagle, then rerun `bridge ping` or `bridge doctor` to refresh the heartbeat.")
    if summary.get("status") is None and not summary.get("status_error"):
        suggestions.append("Open Eagle once so the companion plugin can publish its bridge status file.")
    if summary.get("queue_depth", 0) > 0:
        suggestions.append("Inspect the backlog with `bridge status` and prune stale files with `bridge cleanup --dry-run` if needed.")
    if ping is not None and ping.get("status") in {"timeout", "error"}:
        suggestions.append("If ping still fails, reinstall the companion plugin and restart Eagle.")
    return suggestions


def _bridge_response_data(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "success":
        return {}
    response = (result.get("data") or {}).get("response") or {}
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _bridge_ping_probe(base_url: str, *, timeout_seconds: float) -> dict[str, Any]:
    try:
        return _bridge_request("ping", {"base_url": base_url}, timeout_seconds=timeout_seconds, queue_only=False)
    except click.ClickException as exc:
        message = str(exc)
        return {
            "status": "timeout" if "Timed out waiting" in message else "error",
            "error": message,
        }


def _bridge_select_items_result(
    app: AppContext,
    *,
    command_name: str,
    item_ids: list[str],
    bridge_timeout: float,
    queue_only: bool,
    extra_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(str(item_id) for item_id in item_ids if str(item_id)))
    if not unique_ids:
        raise click.ClickException(f"{command_name} did not resolve any item IDs.")
    data = {
        "requested_count": len(unique_ids),
        "sample_ids": unique_ids[:20],
        **(extra_data or {}),
    }
    if app.dry_run:
        return {"status": "dry-run", "data": data}
    bridge_result = _bridge_request(
        "select_items",
        {"item_ids": unique_ids},
        timeout_seconds=bridge_timeout,
        queue_only=queue_only,
    )
    payload = _bridge_response_data(bridge_result)
    return {
        "status": bridge_result.get("status", "success"),
        "data": {
            **data,
            "selected_count": payload.get("selected_count", payload.get("requested_count", len(unique_ids))),
            "bridge": bridge_result["data"],
            "response": payload,
        },
    }


def _save_current_selection_result(app: AppContext, *, name: str, item_limit: int, bridge_timeout: float) -> dict[str, Any]:
    bridge_result = _bridge_request("get_context", {"item_limit": item_limit}, timeout_seconds=bridge_timeout, queue_only=False)
    payload = _bridge_response_data(bridge_result)
    item_ids = [str(item.get("id")) for item in payload.get("selected_items") or [] if str(item.get("id"))]
    if not item_ids:
        raise click.ClickException("No selected Eagle items were returned by the companion plugin.")
    data = {
        "name": name,
        "item_count": len(item_ids),
        "sample_ids": item_ids[:10],
        "selected_folder_count": payload.get("selected_folder_count", 0),
        "request_id": bridge_result["data"].get("request_id"),
    }
    if app.dry_run:
        return {"status": "dry-run", "data": data}
    path = _save_selection(
        name,
        item_ids,
        context={
            "source": "bridge-capture",
            "selected_folder_count": payload.get("selected_folder_count", 0),
            "selected_folders": payload.get("selected_folders") or [],
        },
    )
    return {
        "status": "success",
        "data": {
            **data,
            "saved_to": str(path),
        },
    }


def _bridge_request(
    action: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    queue_only: bool,
) -> dict[str, Any]:
    request = write_bridge_request(action, payload)
    if queue_only:
        return {
            "status": "queued",
            "data": {
                "request_id": request["request_id"],
                "request_path": str(request["request_path"]),
                "response_path": str(request["response_path"]),
                "action": action,
            },
        }

    response = wait_for_bridge_response(request["request_id"], timeout_seconds=timeout_seconds)
    if response is None:
        summary = _bridge_status_payload()
        detail_parts = [f"Request file: {request['request_path']}."]
        heartbeat_age = summary.get("heartbeat_age_seconds")
        if not summary.get("installed_plugin_paths"):
            detail_parts.append("Bridge plugin is not installed; run `bridge install-plugin`.")
        elif summary.get("health") != "healthy":
            detail_parts.append("Bridge plugin appears installed but is not healthy; restart Eagle and rerun `bridge doctor`.")
        if heartbeat_age is not None:
            detail_parts.append(f"Heartbeat age: {heartbeat_age:.1f}s.")
        elif summary.get("status_error"):
            detail_parts.append(f"Status file error: {summary.get('status_error')}.")
        elif summary.get("status") is None:
            detail_parts.append("No bridge status file has been written yet.")
        if summary.get("pending_request_count"):
            detail_parts.append(f"Pending requests: {summary.get('pending_request_count')}.")
        if summary.get("pending_response_count"):
            detail_parts.append(f"Pending responses: {summary.get('pending_response_count')}.")
        raise click.ClickException(
            f"Timed out waiting for the Eagle bridge plugin to process '{action}'. "
            f"{' '.join(detail_parts)} Use `bridge doctor`, `bridge status`, and `bridge install-plugin` if needed."
        )
    if response.get("status") == "error":
        raise click.ClickException(f"Bridge request '{action}' failed: {response.get('error', 'unknown error')}")
    return {
        "status": "success",
        "data": {
            "request_id": request["request_id"],
            "response": response,
        },
    }


def _build_rename_operations(
    items: list[dict[str, Any]],
    *,
    prefix: str,
    suffix: str,
    replace_from: str | None,
    replace_to: str | None,
    regex_from: str | None,
    regex_to: str | None,
    name_template: str | None,
    strip_names: bool,
    skip_unchanged: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not any([prefix, suffix, replace_from is not None, regex_from, name_template, strip_names]):
        raise click.ClickException(
            "Provide at least one rename transform such as --prefix, --suffix, --replace-from, --regex-from, --name-template, or --strip."
        )
    operations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        current_name = str(item.get("name") or "")
        next_name = current_name
        if replace_from is not None:
            next_name = next_name.replace(replace_from, replace_to or "")
        if regex_from:
            next_name = re.sub(regex_from, regex_to or "", next_name)
        if strip_names:
            next_name = next_name.strip()
        if name_template:
            try:
                next_name = name_template.format(
                    name=next_name,
                    original=current_name,
                    ext=str(item.get("ext") or ""),
                    id=str(item.get("id") or ""),
                    index=index,
                )
            except KeyError as exc:
                raise click.ClickException(f"Unsupported rename template field: {exc.args[0]}") from exc
        next_name = f"{prefix}{next_name}{suffix}"
        if not next_name:
            skipped.append({"id": item.get("id"), "name": current_name, "reason": "empty-result"})
            continue
        if next_name == current_name and skip_unchanged:
            skipped.append({"id": item.get("id"), "name": current_name, "reason": "unchanged"})
            continue
        if next_name == current_name:
            skipped.append({"id": item.get("id"), "name": current_name, "reason": "unchanged"})
            continue
        operations.append(
            {
                "item_id": item.get("id"),
                "name": current_name,
                "new_name": next_name,
            }
        )
    return operations, skipped


def _build_move_operations(
    items: list[dict[str, Any]],
    *,
    target_folder_id: str,
    target_folder_path: str,
    skip_unchanged: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    operations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in items:
        current_folders = [str(folder_id) for folder_id in item.get("folders") or [] if str(folder_id)]
        if current_folders == [target_folder_id] and skip_unchanged:
            skipped.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "reason": "already-in-target-folder",
                }
            )
            continue
        if current_folders == [target_folder_id]:
            skipped.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "reason": "already-in-target-folder",
                }
            )
            continue
        operations.append(
            {
                "item_id": item.get("id"),
                "name": item.get("name"),
                "current_folders": current_folders,
                "folder_ids": [target_folder_id],
                "target_folder_path": target_folder_path,
            }
        )
    return operations, skipped


def _minimal_item_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "ext": item.get("ext"),
        "size": item.get("size"),
        "folders": item.get("folders") or [],
        "tags": item.get("tags") or [],
        "url": item.get("url"),
    }


def _build_duplicate_report(items: list[dict[str, Any]], *, modes: tuple[str, ...], top: int) -> dict[str, Any]:
    report: dict[str, Any] = {"total_items": len(items), "modes": []}
    for mode in modes:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            key = _duplicate_key(item, mode)
            if key is None:
                continue
            buckets.setdefault(key, []).append(item)
        groups = [
            {
                "key": key,
                "count": len(group_items),
                "items": [_minimal_item_row(item) for item in group_items[:top]],
            }
            for key, group_items in buckets.items()
            if len(group_items) > 1
        ]
        groups.sort(key=lambda row: (-row["count"], row["key"]))
        report["modes"].append(
            {
                "mode": mode,
                "group_count": len(groups),
                "groups": groups[:top],
            }
        )
    return report


def _duplicate_key(item: dict[str, Any], mode: str) -> str | None:
    name = str(item.get("name") or "").strip()
    url = str(item.get("url") or "").strip()
    ext = str(item.get("ext") or "").strip().lower()
    size = item.get("size")
    if mode == "name":
        return name or None
    if mode == "url":
        return url or None
    if mode == "name-size":
        if not name or size in (None, ""):
            return None
        return f"{name}|{size}"
    if mode == "name-ext":
        if not name or not ext:
            return None
        return f"{name}|{ext}"
    raise click.ClickException(f"Unsupported duplicate mode: {mode}")


def _build_cleanup_report(items: list[dict[str, Any]], *, sample_limit: int) -> dict[str, Any]:
    untagged = [_minimal_item_row(item) for item in items if not list(item.get("tags") or [])]
    unfiled = [_minimal_item_row(item) for item in items if not list(item.get("folders") or [])]
    missing_annotation = [_minimal_item_row(item) for item in items if not str(item.get("annotation") or "").strip()]
    missing_url = [_minimal_item_row(item) for item in items if not str(item.get("url") or "").strip()]
    deleted = [_minimal_item_row(item) for item in items if bool(item.get("isDeleted"))]
    return {
        "total_items": len(items),
        "counts": {
            "untagged": len(untagged),
            "unfiled": len(unfiled),
            "missing_annotation": len(missing_annotation),
            "missing_url": len(missing_url),
            "deleted": len(deleted),
        },
        "samples": {
            "untagged": untagged[:sample_limit],
            "unfiled": unfiled[:sample_limit],
            "missing_annotation": missing_annotation[:sample_limit],
            "missing_url": missing_url[:sample_limit],
            "deleted": deleted[:sample_limit],
        },
    }


def _build_dedupe_plan_report(
    items: list[dict[str, Any]],
    *,
    mode: str,
    keep: str,
    batch_size: int,
) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = _duplicate_key(item, mode)
        if key is None:
            continue
        buckets.setdefault(key, []).append(item)

    duplicate_groups: list[dict[str, Any]] = []
    trash_ids: list[str] = []
    for key, group_items in buckets.items():
        if len(group_items) < 2:
            continue
        keeper = _choose_duplicate_keeper(group_items, keep=keep)
        discard = [item for item in group_items if str(item.get("id")) != str(keeper.get("id"))]
        trash_ids.extend(str(item.get("id")) for item in discard if str(item.get("id")))
        duplicate_groups.append(
            {
                "key": key,
                "count": len(group_items),
                "keep": _minimal_item_row(keeper),
                "trash": [_minimal_item_row(item) for item in discard],
            }
        )

    unique_trash_ids = _unique_preserve_order(trash_ids)
    operations = [
        _make_operation(
            "POST",
            "/api/item/moveToTrash",
            {"itemIds": batch},
            description=f"Move {len(batch)} duplicate item(s) to trash",
        )
        for batch in _chunked(unique_trash_ids, batch_size)
    ]
    duplicate_groups.sort(key=lambda row: (-row["count"], row["key"]))
    return {
        "mode": mode,
        "keep": keep,
        "group_count": len(duplicate_groups),
        "trash_count": len(unique_trash_ids),
        "duplicate_groups": duplicate_groups,
        "operations": operations,
    }


def _choose_duplicate_keeper(group_items: list[dict[str, Any]], *, keep: str) -> dict[str, Any]:
    if keep == "first":
        return group_items[0]
    if keep == "last":
        return group_items[-1]
    if keep == "largest":
        return max(group_items, key=lambda item: (int(item.get("size") or 0), str(item.get("id") or "")))
    if keep == "smallest":
        return min(group_items, key=lambda item: (int(item.get("size") or 0), str(item.get("id") or "")))
    if keep == "newest":
        return max(group_items, key=lambda item: (_item_sort_timestamp(item), str(item.get("id") or "")))
    if keep == "oldest":
        return min(group_items, key=lambda item: (_item_sort_timestamp(item), str(item.get("id") or "")))
    raise click.ClickException(f"Unsupported duplicate keep strategy: {keep}")


def _item_sort_timestamp(item: dict[str, Any]) -> int:
    for key in ["modificationTime", "mtime", "btime"]:
        value = item.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _build_snapshot_diff_report(
    document: dict[str, Any],
    *,
    app: AppContext,
    include_names: bool,
    include_folders: bool,
) -> dict[str, Any]:
    snapshot_items = list(document.get("items") or [])
    item_ids = tuple(str(item.get("id")) for item in snapshot_items if str(item.get("id")))
    current_items = (
        _collect_target_items(
            app,
            item_ids=item_ids,
            fetch_all=False,
            limit=len(item_ids) or 1,
            offset=0,
            order_by=None,
            keyword=None,
            ext=None,
            tags=(),
            folders=(),
            folder_names=(),
            folder_paths=(),
        )
        if item_ids
        else []
    )
    current_by_id = {str(item.get("id")): item for item in current_items}

    changed: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    unchanged = 0
    for snapshot_item in snapshot_items:
        item_id = str(snapshot_item.get("id") or "")
        current_item = current_by_id.get(item_id)
        if current_item is None:
            missing.append({"id": item_id, "name": snapshot_item.get("name"), "reason": "missing"})
            continue
        differences = _snapshot_item_differences(
            snapshot_item,
            current_item,
            include_names=include_names,
            include_folders=include_folders,
        )
        if differences:
            changed.append(
                {
                    "id": item_id,
                    "name": current_item.get("name"),
                    "differences": differences,
                }
            )
        else:
            unchanged += 1

    return {
        "kind": "eagle-cli-snapshot-diff",
        "snapshot": _snapshot_summary(document),
        "counts": {
            "snapshot_items": len(snapshot_items),
            "matched_items": len(current_items),
            "changed_items": len(changed),
            "missing_items": len(missing),
            "unchanged_items": unchanged,
        },
        "changed": changed,
        "missing": missing,
    }


def _snapshot_item_differences(
    snapshot_item: dict[str, Any],
    current_item: dict[str, Any],
    *,
    include_names: bool,
    include_folders: bool,
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    metadata_payload = {
        "tags": list(snapshot_item.get("tags") or []),
        "annotation": snapshot_item.get("annotation"),
        "url": snapshot_item.get("url"),
        "star": snapshot_item.get("star"),
    }
    for field in _changed_item_fields(current_item, {"id": current_item.get("id"), **metadata_payload}):
        differences.append({"field": field, "snapshot": metadata_payload.get(field), "current": current_item.get(field)})
    if include_names and str(snapshot_item.get("name") or "") != str(current_item.get("name") or ""):
        differences.append({"field": "name", "snapshot": snapshot_item.get("name"), "current": current_item.get("name")})
    if include_folders:
        snapshot_folders = [str(folder_id) for folder_id in snapshot_item.get("folders") or [] if str(folder_id)]
        current_folders = [str(folder_id) for folder_id in current_item.get("folders") or [] if str(folder_id)]
        if snapshot_folders != current_folders:
            differences.append({"field": "folders", "snapshot": snapshot_folders, "current": current_folders})
    return differences


def _resolve_move_target(
    app: AppContext,
    *,
    target_folder_id: str | None,
    target_folder_name: str | None,
    target_folder_path: str | None,
    ensure_target_path: str | None,
) -> tuple[dict[str, Any], FolderRecord | None]:
    selectors = [value for value in [target_folder_id, target_folder_name, target_folder_path, ensure_target_path] if value]
    if len(selectors) != 1:
        raise click.ClickException("Use exactly one move target selector: --target-folder-id, --target-folder-name, --target-folder-path, or --ensure-target-path.")
    if ensure_target_path:
        ensure_result = _ensure_folder_path(app, ensure_target_path)
        folder = FolderRecord(
            id=str(ensure_result["data"].get("leaf_id") or ""),
            name=normalize_folder_path(ensure_result["data"].get("leaf_path") or "").split("/")[-1],
            path=str(ensure_result["data"].get("leaf_path") or ""),
            depth=str(ensure_result["data"].get("leaf_path") or "").count("/"),
            parent_id=None,
            parent_path=None,
            raw={},
        )
        return ensure_result, folder
    folder = _resolve_folder_selector(
        app,
        folder_id=target_folder_id,
        folder_name=target_folder_name,
        folder_path=target_folder_path,
        purpose="target folder",
        required=True,
    )
    return {"status": "success", "data": {"leaf_id": folder.id, "leaf_path": folder.path}}, folder


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _collect_target_items(
    app: AppContext,
    *,
    item_ids: tuple[str, ...],
    fetch_all: bool = False,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> list[dict[str, Any]]:
    if item_ids:
        return [app.client.item_info(item_id)["data"] for item_id in item_ids]
    query = _query_items(
        app,
        fetch_all=fetch_all,
        limit=limit,
        offset=offset,
        order_by=order_by,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    return list(query["items"])


def _item_selector_context(
    *,
    item_ids: tuple[str, ...],
    fetch_all: bool,
    limit: int,
    offset: int,
    order_by: str | None,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> dict[str, Any]:
    if item_ids:
        return {"item_ids": list(item_ids)}
    return {
        "fetch_all": fetch_all,
        "filters": _item_filter_payload_from_args(
            limit=limit,
            offset=offset,
            order_by=order_by,
            keyword=keyword,
            ext=ext,
            tags=tags,
            folders=folders,
            folder_names=folder_names,
            folder_paths=folder_paths,
        ),
    }


def _snapshot_restore_operations(
    metadata_operations: list[dict[str, Any]],
    rename_operations: list[dict[str, Any]],
    move_operations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    operations = list(metadata_operations)
    if rename_operations:
        operations.append(_make_bridge_operation("rename_items", {"operations": rename_operations}, description="Restore item names from snapshot"))
    if move_operations:
        operations.append(_make_bridge_operation("move_items", {"operations": move_operations}, description="Restore item folders from snapshot"))
    return operations


def _organize_plan_operations(
    *,
    metadata_result: dict[str, Any] | None,
    rename_operations: list[dict[str, Any]],
    move_operations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    if isinstance(metadata_result, dict):
        operations.extend(_extract_operations_from_document(metadata_result))
    if rename_operations:
        operations.append(_make_bridge_operation("rename_items", {"operations": rename_operations}, description="Apply organize rename operations"))
    if move_operations:
        operations.append(_make_bridge_operation("move_items", {"operations": move_operations}, description="Apply organize move operations"))
    return operations


def _resolve_item_selector_ids(
    app: AppContext,
    *,
    item_ids: tuple[str, ...],
    item_file: Path | None,
    use_last: bool,
) -> tuple[str, ...]:
    resolved = [str(item_id) for item_id in item_ids if str(item_id)]
    if item_file is not None:
        resolved.extend(_load_item_ids_from_file(item_file))
    if use_last:
        if not app.state.last_item_ids:
            raise click.ClickException("No item IDs are available from the last command.")
        resolved.extend(str(item_id) for item_id in app.state.last_item_ids if str(item_id))
    return tuple(_unique_preserve_order(resolved))


def _load_item_ids_from_file(path: Path) -> list[str]:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids = _extract_item_ids_from_document(payload)
    elif suffix == ".jsonl":
        ids = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.extend(_extract_item_ids_from_document(json.loads(line)))
    elif suffix == ".csv":
        ids = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("id"):
                    ids.append(str(row["id"]))
                if row.get("item_id"):
                    ids.append(str(row["item_id"]))
                if row.get("itemIds"):
                    ids.extend(part.strip() for part in str(row["itemIds"]).split(",") if part.strip())
    else:
        ids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    resolved = _unique_preserve_order([item_id for item_id in ids if item_id])
    if not resolved:
        raise click.ClickException(f"Could not find any item IDs in {path}.")
    return resolved


def _extract_item_ids_from_document(value: Any) -> list[str]:
    ids: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            item_ids = node.get("itemIds")
            if isinstance(item_ids, list):
                ids.extend(str(item_id) for item_id in item_ids if str(item_id))
            single_item_id = node.get("item_id")
            if isinstance(single_item_id, str) and single_item_id:
                ids.append(single_item_id)
            plural_ids = node.get("item_ids")
            if isinstance(plural_ids, list):
                ids.extend(str(item_id) for item_id in plural_ids if str(item_id))
            node_id = node.get("id")
            if isinstance(node_id, str) and node_id and _node_looks_like_item(node):
                ids.append(node_id)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return _unique_preserve_order(ids)


def _node_looks_like_item(node: dict[str, Any]) -> bool:
    if "children" in node or "extendTags" in node:
        return False
    item_markers = {
        "annotation",
        "ext",
        "folders",
        "isDeleted",
        "palettes",
        "size",
        "star",
        "tags",
        "url",
    }
    if item_markers.intersection(node.keys()):
        return True
    folder_markers = {"depth", "parent_id", "parent_path", "leaf_id", "folder_id"}
    if "id" in node and "name" in node and "payload" not in node and not folder_markers.intersection(node.keys()):
        return True
    return False


def _apply_item_guardrails(
    items: list[dict[str, Any]],
    *,
    max_items: int | None,
    require_match: int | None,
    save_matches: Path | None,
) -> int:
    matched_count = len(items)
    if require_match is not None and matched_count < require_match:
        raise click.ClickException(f"Matched {matched_count} item(s), which is below the required minimum of {require_match}.")
    if max_items is not None and matched_count > max_items:
        raise click.ClickException(f"Matched {matched_count} item(s), which exceeds --max-items {max_items}.")
    if save_matches is not None:
        _write_items_export(save_matches, items, "auto")
    return matched_count


def _resolve_folder_filters(
    app: AppContext,
    *,
    folder_ids: list[str],
    folder_names: list[str],
    folder_paths: list[str],
) -> list[str]:
    if not any([folder_ids, folder_names, folder_paths]):
        return []
    if folder_ids and not any([folder_names, folder_paths]):
        return _unique_preserve_order(folder_ids)
    records = _folder_records(app)
    resolved = list(folder_ids)
    for folder_name in folder_names:
        record = _resolve_folder_record_from_records(
            records,
            folder_name=folder_name,
            purpose=f"folder name '{folder_name}'",
        )
        resolved.append(record.id)
    for folder_path in folder_paths:
        record = _resolve_folder_record_from_records(
            records,
            folder_path=folder_path,
            purpose=f"folder path '{folder_path}'",
        )
        resolved.append(record.id)
    return _unique_preserve_order(resolved)


def _resolve_folder_selector(
    app: AppContext,
    *,
    folder_id: str | None = None,
    folder_name: str | None = None,
    folder_path: str | None = None,
    purpose: str,
    required: bool,
) -> FolderRecord | None:
    records = _folder_records(app) if any([folder_id, folder_name, folder_path]) else []
    return _resolve_folder_record_from_records(
        records,
        folder_id=folder_id,
        folder_name=folder_name,
        folder_path=folder_path,
        purpose=purpose,
        required=required,
    )


def _resolve_folder_record_from_records(
    records: list[FolderRecord],
    *,
    folder_id: str | None = None,
    folder_name: str | None = None,
    folder_path: str | None = None,
    purpose: str,
    required: bool = True,
) -> FolderRecord | None:
    selected = [value for value in [folder_id, folder_name, folder_path] if value]
    if len(selected) > 1:
        raise click.ClickException(f"Use only one selector for {purpose}: ID, name, or path.")
    if not selected:
        if required:
            raise click.ClickException(f"Missing selector for {purpose}.")
        return None

    if folder_id:
        for record in records:
            if record.id == folder_id:
                return record
        raise click.ClickException(f"Unknown {purpose} ID: {folder_id}")

    if folder_path:
        match = find_folder_by_path(records, folder_path)
        if match is None:
            raise click.ClickException(f"Could not find {purpose} path: {normalize_folder_path(folder_path)}")
        return match

    matches = find_folders_by_name(records, folder_name or "", exact=True)
    if not matches:
        raise click.ClickException(f"Could not find exact {purpose} name: {folder_name}. Try `folder find` first.")
    if len(matches) > 1:
        paths = ", ".join(match.path for match in matches)
        raise click.ClickException(f"Ambiguous {purpose} name '{folder_name}'. Matches: {paths}")
    return matches[0]


def _ensure_folder_path(
    app: AppContext,
    folder_path: str,
    *,
    parent: FolderRecord | None = None,
    description: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_folder_path(folder_path)
    if not normalized:
        raise click.ClickException("Folder path cannot be empty.")

    records = _folder_records(app)
    parent_id = parent.id if parent else None
    parent_path = parent.path if parent else None

    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    planned: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    previous_parent_id = parent_id
    previous_parent_path = parent_path
    leaf_id: str | None = None
    leaf_path: str | None = None

    for segment in normalized.split("/"):
        matches = find_folders_by_name(records, segment, exact=True, parent_id=previous_parent_id)
        if len(matches) > 1:
            options = ", ".join(match.path for match in matches)
            raise click.ClickException(f"Ambiguous folder segment '{segment}'. Matches: {options}")

        if matches:
            current = matches[0]
            reused.append(_folder_row(current))
            previous_parent_id = current.id
            previous_parent_path = current.path
            leaf_id = current.id
            leaf_path = current.path
            continue

        path_value = f"{previous_parent_path}/{segment}" if previous_parent_path else segment
        payload = {"folderName": segment}
        if previous_parent_id:
            payload["parent"] = previous_parent_id
        operations.append(
            _make_operation(
                "POST",
                "/api/folder/create",
                payload,
                description=f"Create folder segment '{segment}' under '{previous_parent_path or '<root>'}'",
            )
        )

        if app.dry_run:
            planned_folder = {
                "id": f"dry-run:{path_value}",
                "name": segment,
                "path": path_value,
                "depth": path_value.count("/"),
                "parent_id": previous_parent_id or "",
            }
            planned.append({"endpoint": "/api/folder/create", "payload": payload, "folder": planned_folder})
            previous_parent_id = planned_folder["id"]
            previous_parent_path = path_value
            leaf_id = planned_folder["id"]
            leaf_path = path_value
            continue

        response = app.client.folder_create(segment, parent=previous_parent_id)
        raw_folder = response["data"]
        current = FolderRecord(
            id=str(raw_folder.get("id", "")),
            name=str(raw_folder.get("name", segment)),
            path=path_value,
            depth=path_value.count("/"),
            parent_id=previous_parent_id,
            parent_path=previous_parent_path,
            raw=raw_folder,
        )
        created.append(_folder_row(current))
        records.append(current)
        previous_parent_id = current.id
        previous_parent_path = current.path
        leaf_id = current.id
        leaf_path = current.path

    leaf_update = None
    if leaf_id and any([description is not None, color is not None]):
        update_payload: dict[str, Any] = {"folderId": leaf_id}
        if description is not None:
            update_payload["newDescription"] = description
        if color is not None:
            update_payload["newColor"] = color
        operations.append(
            _make_operation(
                "POST",
                "/api/folder/update",
                update_payload,
                description=f"Update ensured folder '{leaf_path}'",
            )
        )
        if app.dry_run:
            planned.append({"endpoint": "/api/folder/update", "payload": update_payload, "folder_id": leaf_id})
            leaf_update = {"planned": True, "payload": update_payload}
        else:
            response = app.client.folder_update(leaf_id, new_description=description, new_color=color)
            leaf_update = response.get("data")

    status = "dry-run" if app.dry_run else "success"
    return {
        "status": status,
        "data": {
            "leaf_id": leaf_id,
            "leaf_path": leaf_path,
            "reused": reused,
            "created": created,
            "planned": planned,
            "operations": operations,
            "leaf_update": leaf_update,
        },
    }


def _folder_records(app: AppContext) -> list[FolderRecord]:
    payload = app.client.folder_list()
    return _folder_records_from_payload(payload)


def _folder_records_from_payload(payload: dict[str, Any]) -> list[FolderRecord]:
    return flatten_folders(payload.get("data") or [])


def _folder_row(record: FolderRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "id": record.id,
        "name": record.name,
        "path": record.path,
        "depth": record.depth,
        "parent_id": record.parent_id or "",
    }


def _library_info_data(app: AppContext) -> dict[str, Any]:
    return app.client.library_info().get("data") or {}


def _smart_folder_records(app: AppContext) -> list[SmartFolderRecord]:
    return _smart_folder_records_from_data(_library_info_data(app).get("smartFolders") or [])


def _smart_folder_records_from_data(data: list[dict[str, Any]]) -> list[SmartFolderRecord]:
    return flatten_smart_folders(data)


def _smart_folder_row(record: SmartFolderRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    conditions = record.raw.get("conditions") or []
    return {
        "id": record.id,
        "name": record.name,
        "path": record.path,
        "depth": record.depth,
        "parent_id": record.parent_id or "",
        "icon": record.raw.get("icon", ""),
        "condition_count": len(conditions) if isinstance(conditions, list) else 0,
        "rule_count": len(smart_folder_rule_rows([record])),
    }


def _resolve_smart_folder_selector(
    app: AppContext,
    *,
    smart_folder_id: str | None = None,
    smart_folder_name: str | None = None,
    smart_folder_path: str | None = None,
    purpose: str,
    required: bool,
) -> SmartFolderRecord | None:
    records = _smart_folder_records(app) if any([smart_folder_id, smart_folder_name, smart_folder_path]) else []
    return _resolve_smart_folder_record_from_records(
        records,
        smart_folder_id=smart_folder_id,
        smart_folder_name=smart_folder_name,
        smart_folder_path=smart_folder_path,
        purpose=purpose,
        required=required,
    )


def _resolve_smart_folder_record_from_records(
    records: list[SmartFolderRecord],
    *,
    smart_folder_id: str | None = None,
    smart_folder_name: str | None = None,
    smart_folder_path: str | None = None,
    purpose: str,
    required: bool = True,
) -> SmartFolderRecord | None:
    selected = [value for value in [smart_folder_id, smart_folder_name, smart_folder_path] if value]
    if len(selected) > 1:
        raise click.ClickException(f"Use only one selector for {purpose}: ID, name, or path.")
    if not selected:
        if required:
            raise click.ClickException(f"Missing selector for {purpose}.")
        return None

    if smart_folder_id:
        for record in records:
            if record.id == smart_folder_id:
                return record
        raise click.ClickException(f"Unknown {purpose} ID: {smart_folder_id}")

    if smart_folder_path:
        match = find_smart_folder_by_path(records, smart_folder_path)
        if match is None:
            raise click.ClickException(f"Could not find {purpose} path: {normalize_folder_path(smart_folder_path)}")
        return match

    matches = find_smart_folders_by_name(records, smart_folder_name or "", exact=True)
    if not matches:
        raise click.ClickException(f"Could not find exact {purpose} name: {smart_folder_name}. Try `smart-folder list` first.")
    if len(matches) > 1:
        paths = ", ".join(match.path for match in matches)
        raise click.ClickException(f"Ambiguous {purpose} name '{smart_folder_name}'. Matches: {paths}")
    return matches[0]


def _tag_groups(app: AppContext) -> list[dict[str, Any]]:
    return list(_library_info_data(app).get("tagsGroups") or [])


def _resolve_tag_group(app: AppContext, *, group_id: str | None, group_name: str | None) -> dict[str, Any]:
    selected = [value for value in [group_id, group_name] if value]
    if len(selected) > 1:
        raise click.ClickException("Use either --id or --name for tag groups, not both.")
    if not selected:
        raise click.ClickException("Missing selector for tag group. Use --id or --name.")
    groups = _tag_groups(app)
    if group_id:
        for group in groups:
            if str(group.get("id", "")) == group_id:
                return group
        raise click.ClickException(f"Unknown tag group ID: {group_id}")
    matches = [group for group in groups if str(group.get("name", "")).casefold() == str(group_name).casefold()]
    if not matches:
        raise click.ClickException(f"Could not find exact tag group name: {group_name}")
    if len(matches) > 1:
        ids = ", ".join(str(group.get("id", "")) for group in matches)
        raise click.ClickException(f"Ambiguous tag group name '{group_name}'. Matching IDs: {ids}")
    return matches[0]


def _parse_kv_pairs(items: tuple[str, ...]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise click.ClickException(f"Invalid key=value pair: {item}")
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed


def _load_payload(*, body_json: str | None, body_file: str | None) -> dict | list | None:
    if body_json and body_file:
        raise click.ClickException("Use either --body-json or --body-file, not both.")
    if body_json:
        return json.loads(body_json)
    if body_file:
        return json.loads(Path(body_file).read_text(encoding="utf-8"))
    return None


def _preset_bundle_presets(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("presets"), dict):
        return payload["presets"]
    if isinstance(payload, dict) and payload and all(isinstance(value, dict) for value in payload.values()):
        return payload
    raise click.ClickException("Preset bundle must be a JSON object with a 'presets' mapping.")


def _load_batch_items_from_paths(
    paths: tuple[str, ...],
    manifest: str | None,
    *,
    website: str | None,
    tags: list[str] | None,
    annotation: str | None,
) -> list[dict]:
    if manifest:
        payload = json.loads(Path(manifest).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            items = payload.get("items")
            if not isinstance(items, list):
                raise click.ClickException("Manifest object must contain an 'items' array.")
            return items
        if isinstance(payload, list):
            return payload
        raise click.ClickException("Manifest must be a JSON array or an object with an 'items' array.")
    if not paths:
        raise click.ClickException("Provide at least one --path or a --manifest.")
    return [
        {
            "path": path,
            "name": Path(path).stem,
            **({"website": website} if website else {}),
            **({"tags": tags} if tags else {}),
            **({"annotation": annotation} if annotation else {}),
        }
        for path in paths
    ]


def _load_batch_items_from_urls(
    urls: tuple[str, ...],
    manifest: str | None,
    *,
    website: str | None,
    tags: list[str] | None,
    annotation: str | None,
) -> list[dict]:
    if manifest:
        payload = json.loads(Path(manifest).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            items = payload.get("items")
            if not isinstance(items, list):
                raise click.ClickException("Manifest object must contain an 'items' array.")
            return items
        if isinstance(payload, list):
            return payload
        raise click.ClickException("Manifest must be a JSON array or an object with an 'items' array.")
    if not urls:
        raise click.ClickException("Provide at least one --url or a --manifest.")
    return [
        {
            "url": url,
            "name": _derive_name_from_url(url),
            **({"website": website} if website else {}),
            **({"tags": tags} if tags else {}),
            **({"annotation": annotation} if annotation else {}),
        }
        for url in urls
    ]


def _collect_files_from_directory(
    directory: Path,
    *,
    recursive: bool,
    globs: tuple[str, ...],
    extensions: tuple[str, ...],
    include_hidden: bool,
    limit: int | None,
) -> list[Path]:
    patterns = list(globs) or ["*"]
    allowed_extensions = {value.strip().lower().lstrip(".") for value in extensions if value.strip()}
    seen: list[Path] = []
    for pattern in patterns:
        iterator = directory.rglob(pattern) if recursive else directory.glob(pattern)
        for path in iterator:
            if not path.is_file():
                continue
            relative_parts = path.relative_to(directory).parts
            if not include_hidden and any(part.startswith(".") for part in relative_parts):
                continue
            if allowed_extensions and path.suffix.lower().lstrip(".") not in allowed_extensions:
                continue
            if path not in seen:
                seen.append(path)
    files = sorted(seen, key=lambda value: str(value).casefold())
    if limit is not None:
        files = files[:limit]
    if not files:
        raise click.ClickException("No files matched the requested directory filters.")
    return files


def _derive_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = Path(parsed.path).name
    return tail or parsed.netloc or "bookmark"


def _smart_folder_translation_error(record: SmartFolderRecord, translation: dict[str, Any]) -> str:
    reasons = [str(rule.get("reason", "unsupported rule")) for rule in translation.get("unsupported_rules", [])]
    preview = "; ".join(reasons[:3])
    extra = ""
    if len(reasons) > 3:
        extra = f" (+{len(reasons) - 3} more)"
    return (
        f"Smart folder '{record.path}' contains rules that cannot be translated safely. "
        f"Use `--allow-partial` to run only the supported subset. Unsupported: {preview}{extra}"
    )


def _configured_value(app: AppContext, key: str) -> Any:
    return app.config.get(key)


def _effective_export_format(app: AppContext, requested_format: str) -> str:
    if requested_format != "auto":
        return requested_format
    configured = _configured_value(app, "export_format")
    return str(configured) if configured else requested_format


def _effective_report_format(app: AppContext, requested_format: str) -> str:
    if requested_format != "auto":
        return requested_format
    configured = _configured_value(app, "report_format")
    return str(configured) if configured else requested_format


def _effective_completion_shell(app: AppContext, shell_name: str) -> str:
    configured = _configured_value(app, "completion_shell")
    if configured and shell_name == "zsh":
        return str(configured)
    return shell_name


def _effective_watch_state_file(app: AppContext, state_file: Path | None) -> Path | None:
    if state_file is not None:
        return state_file
    configured = _configured_value(app, "watch_state_file")
    return Path(str(configured)).expanduser() if configured else None


def _write_items_export(path: Path, items: list[dict[str, Any]], requested_format: str) -> str:
    export_format = _infer_export_format(path, requested_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    if export_format == "json":
        atomic_write_json(path, items)
        return export_format
    if export_format == "jsonl":
        lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items]
        text = "\n".join(lines)
        if lines:
            text += "\n"
        atomic_write_text(path, text)
        return export_format
    if export_format == "csv":
        columns = _collect_export_columns(items)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            if columns:
                writer.writeheader()
                for item in items:
                    writer.writerow({column: _csv_cell(item.get(column)) for column in columns})
        return export_format
    raise click.ClickException(f"Unsupported export format: {export_format}")


def _summarize_items(app: AppContext, items: list[dict[str, Any]], *, top: int) -> dict[str, Any]:
    from collections import Counter

    ext_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    folder_counts: Counter[str] = Counter()
    star_counts: Counter[str] = Counter()
    folder_path_lookup = {record.id: record.path for record in _folder_records(app)}

    tagged_items = 0
    untagged_items = 0
    annotated_items = 0
    sourced_items = 0
    deleted_items = 0
    multi_folder_items = 0

    for item in items:
        ext_value = str(item.get("ext") or "").lower()
        if ext_value:
            ext_counts[ext_value] += 1

        tags = [str(tag) for tag in item.get("tags") or [] if str(tag)]
        if tags:
            tagged_items += 1
            for tag in tags:
                tag_counts[tag] += 1
        else:
            untagged_items += 1

        folders = [str(folder_id) for folder_id in item.get("folders") or [] if str(folder_id)]
        if len(folders) > 1:
            multi_folder_items += 1
        for folder_id in folders:
            folder_counts[folder_id] += 1

        if str(item.get("annotation") or "").strip():
            annotated_items += 1
        if str(item.get("url") or "").strip():
            sourced_items += 1
        if bool(item.get("isDeleted")):
            deleted_items += 1

        star_value = item.get("star")
        if star_value is not None:
            star_counts[str(star_value)] += 1

    return {
        "total_items": len(items),
        "tagged_items": tagged_items,
        "untagged_items": untagged_items,
        "annotated_items": annotated_items,
        "with_source_url": sourced_items,
        "deleted_items": deleted_items,
        "multi_folder_items": multi_folder_items,
        "extensions": [{"ext": key, "count": value} for key, value in ext_counts.most_common(top)],
        "tags": [{"tag": key, "count": value} for key, value in tag_counts.most_common(top)],
        "folders": [
            {"folder_id": key, "folder_path": folder_path_lookup.get(key, ""), "count": value}
            for key, value in folder_counts.most_common(top)
        ],
        "stars": [{"star": key, "count": value} for key, value in star_counts.most_common(top)],
    }


def _infer_export_format(path: Path, requested_format: str) -> str:
    if requested_format != "auto":
        return requested_format
    suffix = path.suffix.casefold()
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".csv":
        return "csv"
    return "json"


def _collect_export_columns(items: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for item in items:
        for key in item.keys():
            if key not in columns:
                columns.append(key)
    return columns


def _csv_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _sanitize_output(value: Any):
    secret_keys = {"apiToken", "token", "authorization", "password"}
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key in secret_keys:
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = _sanitize_output(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_output(item) for item in value]
    return value


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _make_operation(method: str, endpoint: str, payload: dict[str, Any] | None, *, description: str | None = None) -> dict[str, Any]:
    operation: dict[str, Any] = {"method": method.upper(), "endpoint": endpoint}
    if payload is not None:
        operation["payload"] = payload
    if description:
        operation["description"] = description
    return operation


def _make_bridge_operation(action: str, payload: dict[str, Any], *, description: str | None = None) -> dict[str, Any]:
    operation: dict[str, Any] = {"kind": "bridge", "action": action, "payload": payload}
    if description:
        operation["description"] = description
    return operation


def _plan_document(command_name: str, operations: list[dict[str, Any]], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "eagle-cli-plan",
        "version": 1,
        "command": command_name,
        "context": context or {},
        "operations": operations,
    }


def _write_plan(path: Path, document: dict[str, Any]) -> None:
    atomic_write_json(path, document)


def _save_plan_if_requested(path: Path | None, command_name: str, operations: list[dict[str, Any]], *, context: dict[str, Any] | None = None) -> None:
    if path is None:
        return
    _write_plan(path, _plan_document(command_name, operations, context=context))


def _write_manifest(path: Path, document: dict[str, Any]) -> None:
    atomic_write_json(path, document)


def _extract_operations_from_document(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    operations = data.get("operations")
    if isinstance(operations, list):
        return operations
    nested = data.get("data")
    if isinstance(nested, dict):
        nested_operations = nested.get("operations")
        if isinstance(nested_operations, list):
            return nested_operations
    return []


def _plan_stats(plan_file: Path, data: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    method_counts: dict[str, int] = {}
    endpoint_counts: dict[str, int] = {}
    bridge_action_counts: dict[str, int] = {}
    for operation in operations:
        if operation.get("kind") == "bridge":
            action = str(operation.get("action") or "bridge")
            bridge_action_counts[action] = bridge_action_counts.get(action, 0) + 1
            continue
        method = str(operation.get("method") or "POST").upper()
        endpoint = str(operation.get("endpoint") or "")
        method_counts[method] = method_counts.get(method, 0) + 1
        endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1
    return {
        "plan_file": str(plan_file),
        "kind": data.get("kind"),
        "version": data.get("version"),
        "command": data.get("command"),
        "operation_count": len(operations),
        "http_methods": method_counts,
        "endpoints": endpoint_counts,
        "bridge_actions": bridge_action_counts,
        "context": data.get("context") or {},
    }


def _chunked(items: list[str], size: int) -> list[list[str]]:
    if not items:
        return []
    return [items[index : index + size] for index in range(0, len(items), size)]


def _build_item_update_operations(
    items: list[dict[str, Any]],
    *,
    set_tags: tuple[str, ...] | list[str] = (),
    add_tags: tuple[str, ...] | list[str] = (),
    annotation: str | None = None,
    source_url: str | None = None,
    star: int | None = None,
    skip_unchanged: bool,
    tag_transform=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    operations: list[dict[str, Any]] = []
    skipped_unchanged: list[dict[str, Any]] = []
    for item in items:
        next_tags = None
        if tag_transform is not None:
            next_tags = list(tag_transform(item))
        else:
            next_tags = list(set_tags) if set_tags else None
            if add_tags:
                current_tags = list(item.get("tags") or [])
                for tag in add_tags:
                    if tag not in current_tags:
                        current_tags.append(tag)
                next_tags = current_tags

        payload: dict[str, Any] = {"id": item["id"]}
        if next_tags is not None:
            payload["tags"] = next_tags
        if annotation is not None:
            payload["annotation"] = annotation
        if source_url is not None:
            payload["url"] = source_url
        if star is not None:
            payload["star"] = star

        changed_fields = _changed_item_fields(item, payload)
        if skip_unchanged and not changed_fields:
            skipped_unchanged.append({"id": item.get("id"), "name": item.get("name")})
            continue
        operations.append(
            {
                "method": "POST",
                "item": {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "existing_tags": item.get("tags") or [],
                },
                "endpoint": "/api/item/update",
                "payload": payload,
                "changed_fields": changed_fields,
                "description": f"Update item {item.get('id')} ({item.get('name')})",
            }
        )
    return operations, skipped_unchanged


def _execute_operations(
    app: AppContext,
    operations: list[dict[str, Any]],
    *,
    bridge_timeout: float = DEFAULT_WAIT_SECONDS,
    queue_only: bool = False,
) -> list[dict[str, Any]]:
    results = []
    for operation in operations:
        if operation.get("kind") == "bridge":
            response = _bridge_request(
                operation["action"],
                operation.get("payload") or {},
                timeout_seconds=bridge_timeout,
                queue_only=queue_only,
            )
            results.append(
                {
                    "kind": "bridge",
                    "action": operation["action"],
                    "status": response.get("status", "success"),
                    "description": operation.get("description"),
                }
            )
            continue
        response = app.client.raw_request(
            operation.get("method", "POST"),
            operation["endpoint"],
            payload=operation.get("payload"),
        )
        results.append(
            {
                "kind": "http",
                "endpoint": operation["endpoint"],
                "method": operation.get("method", "POST"),
                "status": response.get("status", "success"),
                "description": operation.get("description"),
            }
        )
    return results


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned or "selection"


def _selection_dir() -> Path:
    path = DEFAULT_STATE_DIR / "selections"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _selection_path(name: str) -> Path:
    return _selection_dir() / f"{_safe_name(name)}.json"


def _selection_document(name: str, item_ids: list[str], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "eagle-cli-selection",
        "version": 1,
        "name": name,
        "created_at": _utc_now(),
        "item_ids": item_ids,
        "item_count": len(item_ids),
        "sample_ids": item_ids[:10],
        "context": context or {},
    }


def _save_selection(name: str, item_ids: list[str], *, context: dict[str, Any] | None = None) -> Path:
    path = _selection_path(name)
    _write_manifest(path, _selection_document(name, item_ids, context=context))
    return path


def _load_selection(name: str) -> dict[str, Any]:
    path = _selection_path(name)
    if not path.exists():
        raise click.ClickException(f"Unknown selection: {name}")
    return _load_data_file(path)


def _list_selections() -> list[dict[str, Any]]:
    selections = []
    for path in sorted(_selection_dir().glob("*.json")):
        payload = _load_data_file(path)
        selections.append(
            {
                "name": payload.get("name") or path.stem,
                "item_count": payload.get("item_count", len(payload.get("item_ids") or [])),
                "created_at": payload.get("created_at"),
                "path": str(path),
            }
        )
    return selections


def _delete_selection(name: str) -> bool:
    path = _selection_path(name)
    if not path.exists():
        return False
    path.unlink()
    return True


def _load_data_file(path: Path) -> Any:
    suffix = path.suffix.casefold()
    text = path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def _find_saved_snapshot_path(node: Any) -> str | None:
    if isinstance(node, dict):
        saved_snapshot = node.get("saved_snapshot")
        if isinstance(saved_snapshot, str) and saved_snapshot:
            return saved_snapshot
        for value in node.values():
            resolved = _find_saved_snapshot_path(value)
            if resolved:
                return resolved
    elif isinstance(node, list):
        for value in node:
            resolved = _find_saved_snapshot_path(value)
            if resolved:
                return resolved
    return None


def _build_tag_stats(items: list[dict[str, Any]], *, top: int) -> dict[str, Any]:
    from collections import Counter

    tag_counts: Counter[str] = Counter()
    tagged_items = 0
    total_tags = 0
    for item in items:
        tags = [str(tag) for tag in item.get("tags") or [] if str(tag)]
        if tags:
            tagged_items += 1
        total_tags += len(tags)
        for tag in tags:
            tag_counts[tag] += 1
    return {
        "total_items": len(items),
        "tagged_items": tagged_items,
        "untagged_items": len(items) - tagged_items,
        "unique_tag_count": len(tag_counts),
        "average_tags_per_item": round(total_tags / len(items), 3) if items else 0.0,
        "rows": [{"tag": tag, "count": count} for tag, count in tag_counts.most_common(top)],
    }


def _build_folder_stats(app: AppContext, items: list[dict[str, Any]], *, top: int) -> dict[str, Any]:
    from collections import Counter

    folder_map = {record.id: record for record in _folder_records(app)}
    counts: Counter[str] = Counter()
    unfiled_items = 0
    for item in items:
        folder_ids = [str(folder_id) for folder_id in item.get("folders") or [] if str(folder_id)]
        if not folder_ids:
            unfiled_items += 1
            continue
        for folder_id in list(dict.fromkeys(folder_ids)):
            counts[folder_id] += 1
    rows = []
    for folder_id, count in counts.most_common(top):
        record = folder_map.get(folder_id)
        rows.append(
            {
                "folder_id": folder_id,
                "folder_name": record.name if record is not None else "",
                "folder_path": record.path if record is not None else "",
                "count": count,
            }
        )
    return {
        "total_items": len(items),
        "unfiled_items": unfiled_items,
        "unique_folder_count": len(counts),
        "rows": rows,
    }


def _normalize_tag_value(
    value: str,
    *,
    lowercase: bool,
    trim: bool,
    collapse_spaces: bool,
) -> str:
    normalized = value
    if trim:
        normalized = normalized.strip()
    if collapse_spaces:
        normalized = re.sub(r"\s+", " ", normalized)
    if lowercase:
        normalized = normalized.lower()
    return normalized


def _build_tag_audit(items: list[dict[str, Any]], *, top: int) -> dict[str, Any]:
    from collections import Counter, defaultdict

    variants: dict[str, set[str]] = defaultdict(set)
    duplicate_items: list[dict[str, Any]] = []
    whitespace_tags: Counter[str] = Counter()
    for item in items:
        tags = [str(tag) for tag in item.get("tags") or [] if str(tag)]
        normalized_seen: list[str] = []
        duplicate_values: list[str] = []
        for tag in tags:
            normalized = _normalize_tag_value(tag, lowercase=True, trim=True, collapse_spaces=True)
            variants[normalized].add(tag)
            if tag != tag.strip() or "  " in tag:
                whitespace_tags[tag] += 1
            if normalized in normalized_seen:
                duplicate_values.append(tag)
            else:
                normalized_seen.append(normalized)
        if duplicate_values:
            duplicate_items.append({"id": item.get("id"), "name": item.get("name"), "duplicate_tags": duplicate_values})
    collisions = [
        {"normalized": normalized, "variants": sorted(values), "count": len(values)}
        for normalized, values in variants.items()
        if len(values) > 1
    ]
    collisions.sort(key=lambda row: (-row["count"], row["normalized"]))
    whitespace_rows = [{"tag": tag, "count": count} for tag, count in whitespace_tags.most_common(top)]
    return {
        "total_items": len(items),
        "normalized_collision_count": len(collisions),
        "duplicate_item_count": len(duplicate_items),
        "collisions": collisions[:top],
        "whitespace_tags": whitespace_rows,
        "duplicate_items": duplicate_items[:top],
    }


def _load_alias_map(path: Path) -> dict[str, str]:
    payload = _load_data_file(path)
    if not isinstance(payload, dict):
        raise click.ClickException("Alias map must be a JSON or YAML object.")
    return {str(key): str(value) for key, value in payload.items()}


def _parse_rename_pairs(values: tuple[str, ...]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise click.ClickException(f"Rename pair must look like old=new: {value}")
        old, new = value.split("=", 1)
        pairs[str(old)] = str(new)
    return pairs


def _tag_transform_from_alias_map(alias_map: dict[str, str], *, lowercase: bool, trim: bool, collapse_spaces: bool):
    def transform(item: dict[str, Any]) -> list[str]:
        next_tags: list[str] = []
        for raw_tag in item.get("tags") or []:
            tag = _normalize_tag_value(str(raw_tag), lowercase=lowercase, trim=trim, collapse_spaces=collapse_spaces)
            if tag in alias_map:
                tag = alias_map[tag]
            if tag and tag not in next_tags:
                next_tags.append(tag)
        return next_tags

    return transform


def _build_cleanup_plan_operations(
    items: list[dict[str, Any]],
    *,
    kinds: tuple[str, ...],
    action: str,
    review_tag: str | None,
    target_folder_id: str | None,
    target_folder_path: str | None,
    batch_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = []
    for item in items:
        reasons = []
        if "untagged" in kinds and not list(item.get("tags") or []):
            reasons.append("untagged")
        if "unfiled" in kinds and not list(item.get("folders") or []):
            reasons.append("unfiled")
        if "missing-url" in kinds and not str(item.get("url") or "").strip():
            reasons.append("missing-url")
        if "missing-annotation" in kinds and not str(item.get("annotation") or "").strip():
            reasons.append("missing-annotation")
        if "deleted" in kinds and bool(item.get("isDeleted")):
            reasons.append("deleted")
        if reasons:
            selected.append({"item": item, "reasons": reasons})

    operations: list[dict[str, Any]] = []
    if action == "add-tag":
        tag_value = review_tag or "needs-review"
        target_items = [row["item"] for row in selected]
        operations, _ = _build_item_update_operations(target_items, add_tags=[tag_value], skip_unchanged=True)
    elif action == "trash":
        item_ids = [str(row["item"].get("id")) for row in selected if str(row["item"].get("id"))]
        operations = [
            _make_operation(
                "POST",
                "/api/item/moveToTrash",
                {"itemIds": batch},
                description=f"Move {len(batch)} cleanup item(s) to trash",
            )
            for batch in _chunked(item_ids, batch_size)
        ]
    elif action == "move-folder":
        if not target_folder_id or not target_folder_path:
            raise click.ClickException("Cleanup move-folder actions require a resolved target folder.")
        move_operations, _ = _build_move_operations(
            [row["item"] for row in selected],
            target_folder_id=target_folder_id,
            target_folder_path=target_folder_path,
            skip_unchanged=True,
        )
        if move_operations:
            operations.append(_make_bridge_operation("move_items", {"operations": move_operations}, description="Move cleanup items"))
    else:
        raise click.ClickException(f"Unsupported cleanup action: {action}")

    return operations, {
        "selected_count": len(selected),
        "sample": [{"item": _minimal_item_row(row["item"]), "reasons": row["reasons"]} for row in selected[:10]],
    }


def _infer_report_format(path: Path, requested_format: str) -> str:
    if requested_format != "auto":
        return requested_format
    suffix = path.suffix.casefold()
    if suffix == ".md":
        return "md"
    if suffix == ".html":
        return "html"
    if suffix == ".csv":
        return "csv"
    return "json"


def _write_report(path: Path, document: dict[str, Any], *, requested_format: str, rows_key: str | None = None) -> str:
    report_format = _infer_report_format(path, requested_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    if report_format == "json":
        atomic_write_json(path, document)
        return report_format
    if report_format == "md":
        atomic_write_text(path, _markdown_report(document, rows_key=rows_key))
        return report_format
    if report_format == "html":
        atomic_write_text(path, _html_report(document, rows_key=rows_key))
        return report_format
    if report_format == "csv":
        rows = list(document.get(rows_key or "rows") or [])
        if not isinstance(rows, list):
            raise click.ClickException("CSV report output requires a row-based report document.")
        columns = _collect_export_columns([row for row in rows if isinstance(row, dict)])
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            if columns:
                writer.writeheader()
                for row in rows:
                    writer.writerow({column: _csv_cell(row.get(column)) for column in columns})
        return report_format
    raise click.ClickException(f"Unsupported report format: {report_format}")


def _markdown_report(document: dict[str, Any], *, rows_key: str | None = None) -> str:
    lines = [f"# {document.get('title', 'CLI-Anything Eagle Report')}", ""]
    for key, value in document.items():
        if key in {"rows", rows_key, "title"}:
            continue
        if isinstance(value, (dict, list)):
            lines.append(f"## {key}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
            lines.append("```")
            lines.append("")
        else:
            lines.append(f"- **{key}**: {value}")
    rows = list(document.get(rows_key or "rows") or [])
    if rows:
        columns = _collect_export_columns([row for row in rows if isinstance(row, dict)])
        lines.extend(["", "## rows", ""])
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(_csv_cell(row.get(column)) for column in columns) + " |")
    lines.append("")
    return "\n".join(lines)


def _html_report(document: dict[str, Any], *, rows_key: str | None = None) -> str:
    import html

    title = html.escape(str(document.get("title", "CLI-Anything Eagle Report")))
    parts = [f"<html><head><meta charset='utf-8'><title>{title}</title></head><body>", f"<h1>{title}</h1>"]
    for key, value in document.items():
        if key in {"rows", rows_key, "title"}:
            continue
        parts.append(f"<h2>{html.escape(str(key))}</h2>")
        if isinstance(value, (dict, list)):
            parts.append(f"<pre>{html.escape(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))}</pre>")
        else:
            parts.append(f"<p>{html.escape(str(value))}</p>")
    rows = list(document.get(rows_key or "rows") or [])
    if rows:
        columns = _collect_export_columns([row for row in rows if isinstance(row, dict)])
        parts.append("<table border='1' cellspacing='0' cellpadding='4'><thead><tr>")
        for column in columns:
            parts.append(f"<th>{html.escape(column)}</th>")
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>")
            for column in columns:
                parts.append(f"<td>{html.escape(_csv_cell(row.get(column)))}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
    parts.append("</body></html>")
    return "".join(parts)


def _trend_rows(items: list[dict[str, Any]], *, bucket: str, field: str) -> list[dict[str, Any]]:
    from collections import Counter
    from datetime import datetime, timezone

    key_map = {"modification": ["modificationTime", "mtime", "lastModified"], "created": ["btime", "mtime"]}
    buckets: Counter[str] = Counter()
    for item in items:
        timestamp = 0
        for key in key_map[field]:
            value = item.get(key)
            if value not in (None, ""):
                try:
                    timestamp = int(value)
                    break
                except (TypeError, ValueError):
                    continue
        if not timestamp:
            continue
        dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        if bucket == "year":
            label = f"{dt.year:04d}"
        else:
            label = f"{dt.year:04d}-{dt.month:02d}"
        buckets[label] += 1
    return [{"bucket": key, "count": buckets[key]} for key in sorted(buckets.keys())]


def _load_workflow(path: Path) -> dict[str, Any]:
    payload = _load_data_file(path)
    if not isinstance(payload, dict):
        raise click.ClickException("Workflow file must be a JSON or YAML object.")
    return payload


def _validate_workflow_document(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("kind") not in (None, "eagle-cli-workflow"):
        errors.append("kind must be 'eagle-cli-workflow' when provided")
    if not isinstance(payload.get("steps"), list) or not payload.get("steps"):
        errors.append("workflow must contain a non-empty 'steps' list")
    supported_actions = {
        "snapshot",
        "export-items",
        "report-tags",
        "report-folders",
        "report-trend",
        "bulk-update",
        "rename",
        "move",
    }
    for index, step in enumerate(payload.get("steps") or []):
        if not isinstance(step, dict):
            errors.append(f"step {index} must be an object")
            continue
        action = step.get("action")
        if action not in supported_actions:
            errors.append(f"step {index} has unsupported action: {action}")
    return {"valid": not errors, "errors": errors}


def _workflow_selector(payload: dict[str, Any]) -> dict[str, Any]:
    selector = dict(payload.get("selection") or {})
    item_ids = tuple(str(item_id) for item_id in selector.get("item_ids") or [] if str(item_id))
    return {
        "item_ids": item_ids,
        "item_file": Path(selector["item_file"]) if selector.get("item_file") else None,
        "use_last": bool(selector.get("last")),
        "fetch_all": bool(selector.get("fetch_all")),
        "limit": int(selector.get("limit", 20)),
        "offset": int(selector.get("offset", 0)),
        "order_by": selector.get("order_by"),
        "keyword": selector.get("keyword"),
        "ext": selector.get("ext"),
        "tags": tuple(selector.get("tags") or []),
        "folders": tuple(selector.get("folders") or []),
        "folder_names": tuple(selector.get("folder_names") or []),
        "folder_paths": tuple(selector.get("folder_paths") or []),
    }


def _workflow_items(app: AppContext, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selector = _workflow_selector(payload)
    _validate_item_selector_request(
        item_ids=selector["item_ids"],
        item_file=selector["item_file"],
        use_last=selector["use_last"],
        fetch_all=selector["fetch_all"],
        keyword=selector["keyword"],
        ext=selector["ext"],
        tags=selector["tags"],
        folders=selector["folders"],
        folder_names=selector["folder_names"],
        folder_paths=selector["folder_paths"],
    )
    resolved_item_ids = _resolve_item_selector_ids(
        app,
        item_ids=selector["item_ids"],
        item_file=selector["item_file"],
        use_last=selector["use_last"],
    )
    query = _query_or_collect_items(
        app,
        item_ids=resolved_item_ids,
        fetch_all=selector["fetch_all"],
        limit=selector["limit"],
        offset=selector["offset"],
        order_by=selector["order_by"],
        keyword=selector["keyword"],
        ext=selector["ext"],
        tags=selector["tags"],
        folders=selector["folders"],
        folder_names=selector["folder_names"],
        folder_paths=selector["folder_paths"],
    )
    return [json.loads(json.dumps(item)) for item in query["items"]], query


def _simulate_http_operations(items: list[dict[str, Any]], operations: list[dict[str, Any]]) -> None:
    by_id = {str(item.get("id")): item for item in items}
    for operation in operations:
        payload = operation.get("payload") or {}
        item_id = str(payload.get("id") or "")
        if item_id and item_id in by_id:
            item = by_id[item_id]
            for key in ["tags", "annotation", "url", "star"]:
                if key in payload:
                    item[key] = payload[key]


def _simulate_rename_operations(items: list[dict[str, Any]], operations: list[dict[str, Any]]) -> None:
    by_id = {str(item.get("id")): item for item in items}
    for operation in operations:
        item_id = str(operation.get("item_id") or "")
        if item_id in by_id:
            by_id[item_id]["name"] = operation.get("new_name")


def _simulate_move_operations(items: list[dict[str, Any]], operations: list[dict[str, Any]]) -> None:
    by_id = {str(item.get("id")): item for item in items}
    for operation in operations:
        item_id = str(operation.get("item_id") or "")
        if item_id in by_id:
            by_id[item_id]["folders"] = list(operation.get("folder_ids") or [])


def _file_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def _watch_state_path(path: Path | None) -> Path:
    if path is not None:
        return path
    target = DEFAULT_STATE_DIR / "watch-import-dir.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _load_watch_state(path: Path | None) -> dict[str, Any]:
    state_path = _watch_state_path(path)
    if not state_path.exists():
        return {"version": 1, "files": {}}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_watch_state(path: Path | None, payload: dict[str, Any]) -> Path:
    state_path = _watch_state_path(path)
    atomic_write_json(state_path, payload)
    return state_path


def _tokenize_name_tags(stem: str) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z0-9가-힣]+", stem) if len(token) >= 2]


def _render_import_name_template(path: Path, root: Path, template: str, index: int) -> str:
    relative = path.relative_to(root)
    return template.format(
        name=path.stem,
        stem=path.stem,
        ext=path.suffix.lstrip("."),
        parent=path.parent.name,
        relative=str(relative),
        relative_stem=str(relative.with_suffix("")),
        index=index,
    )


def _build_add_dir_items(
    directory: Path,
    files: list[Path],
    *,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    name_template: str | None,
    tag_from_path: bool,
    tag_from_name: bool,
) -> list[dict[str, Any]]:
    items = []
    for index, path in enumerate(files, start=1):
        item_tags = list(tags)
        if tag_from_path:
            relative_parent = path.relative_to(directory).parent
            if str(relative_parent) != ".":
                for part in relative_parent.parts:
                    if part not in item_tags:
                        item_tags.append(part)
        if tag_from_name:
            for token in _tokenize_name_tags(path.stem):
                if token not in item_tags:
                    item_tags.append(token)
        item_name = _render_import_name_template(path, directory, name_template, index) if name_template else path.stem
        items.append(
            {
                "path": str(path),
                "name": item_name,
                **({"website": website} if website else {}),
                **({"tags": item_tags} if item_tags else {}),
                **({"annotation": annotation} if annotation else {}),
            }
        )
    return items


def _completion_script(shell: str) -> str:
    env_name = "_CLI_ANYTHING_EAGLE_COMPLETE"
    if shell == "bash":
        return f'eval "$({env_name}=bash_source cli-anything-eagle)"'
    if shell == "zsh":
        return f'eval "$({env_name}=zsh_source cli-anything-eagle)"'
    if shell == "fish":
        return f"{env_name}=fish_source cli-anything-eagle | source"
    raise click.ClickException(f"Unsupported shell: {shell}")


def _schema_document(kind: str) -> dict[str, Any]:
    schemas = {
        "plan": {
            "title": "CLI-Anything Eagle Plan",
            "type": "object",
            "required": ["kind", "version", "operations"],
            "properties": {
                "kind": {"const": "eagle-cli-plan"},
                "version": {"type": "integer"},
                "command": {"type": "string"},
                "context": {"type": "object"},
                "operations": {"type": "array"},
            },
        },
        "snapshot": {
            "title": "CLI-Anything Eagle Snapshot",
            "type": "object",
            "required": ["kind", "version", "items"],
            "properties": {
                "kind": {"const": "eagle-cli-snapshot"},
                "version": {"type": "integer"},
                "created_at": {"type": "string"},
                "items": {"type": "array"},
            },
        },
        "selection": {
            "title": "CLI-Anything Eagle Selection",
            "type": "object",
            "required": ["kind", "version", "name", "item_ids"],
            "properties": {
                "kind": {"const": "eagle-cli-selection"},
                "version": {"type": "integer"},
                "name": {"type": "string"},
                "item_ids": {"type": "array"},
            },
        },
        "workflow": {
            "title": "CLI-Anything Eagle Workflow",
            "type": "object",
            "required": ["steps"],
            "properties": {
                "kind": {"const": "eagle-cli-workflow"},
                "version": {"type": "integer"},
                "selection": {"type": "object"},
                "steps": {"type": "array"},
            },
        },
        "report": {
            "title": "CLI-Anything Eagle Report",
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string"},
                "rows": {"type": "array"},
            },
        },
    }
    if kind not in schemas:
        raise click.ClickException(f"Unsupported schema kind: {kind}")
    return schemas[kind]


@cli.result_callback()
@click.pass_obj
def process_result(_: object, app: AppContext | None, **__: object) -> None:
    if app is None:
        return


def main() -> None:
    try:
        cli()
    except EagleApiError as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
