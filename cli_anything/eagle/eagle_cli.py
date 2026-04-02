from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click

from cli_anything.eagle import __version__
from cli_anything.eagle.core.bridge import (
    BRIDGE_PLUGIN_ID,
    BRIDGE_PLUGIN_NAME,
    DEFAULT_WAIT_SECONDS,
    bridge_layout,
    companion_plugin_template_dir,
    default_plugin_dir_candidates,
    ensure_bridge_dirs,
    export_companion_plugin,
    install_companion_plugin,
    installed_plugin_paths,
    load_bridge_status,
    write_bridge_request,
    wait_for_bridge_response,
)
from cli_anything.eagle.core.client import DEFAULT_BASE_URL, EagleApiError, EagleClient
from cli_anything.eagle.core.state import SessionState
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
    client: EagleClient
    state: SessionState
    json_output: bool
    timeout: float
    base_url: str
    dry_run: bool


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
    resolved_base_url = base_url or os.environ.get("EAGLE_API_BASE_URL") or state.base_url or DEFAULT_BASE_URL
    resolved_timeout = timeout or state.timeout or 15.0

    client = EagleClient(base_url=resolved_base_url, timeout=resolved_timeout)
    ctx.obj = AppContext(
        client=client,
        state=state,
        json_output=json_output,
        timeout=resolved_timeout,
        base_url=resolved_base_url,
        dry_run=dry_run,
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
    layout = ensure_bridge_dirs()
    installed = [str(path) for path in installed_plugin_paths()]
    status = load_bridge_status()
    _emit_and_remember(
        app,
        "bridge status",
        {
            "status": "success",
            "data": {
                "plugin_id": BRIDGE_PLUGIN_ID,
                "plugin_name": BRIDGE_PLUGIN_NAME,
                "template_dir": str(companion_plugin_template_dir()),
                "state_dir": str(layout["state_dir"]),
                "request_dir": str(layout["requests"]),
                "response_dir": str(layout["responses"]),
                "processed_dir": str(layout["processed"]),
                "installed_plugin_paths": installed,
                "default_plugin_dirs": [str(path) for path in default_plugin_dir_candidates()],
                "status": status,
            },
        },
    )


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
    target_root = plugin_dir
    if target_root is None:
        target_root = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    installed_path = install_companion_plugin(target_root)
    _emit_and_remember(
        app,
        "bridge install-plugin",
        {
            "status": "success",
            "data": {
                "installed_to": str(installed_path),
                "plugin_root": str(target_root),
                "plugin_id": BRIDGE_PLUGIN_ID,
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
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
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
@click.option("--all", "fetch_all", is_flag=True, help="Capture all matching items by paging with the current limit as page size.")
@item_filter_options
@pass_app
def snapshot_create(
    app: AppContext,
    output_file: Path,
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
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    items = _collect_target_items(
        app,
        item_ids=item_ids,
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
            "item_ids": list(item_ids),
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


@snapshot.command("restore")
@click.argument("snapshot_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--restore-names", is_flag=True, help="Also restore item names through the bridge plugin.")
@click.option("--restore-folders", is_flag=True, help="Also restore folder assignments through the bridge plugin.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue bridge work without waiting for a response.")
@click.option("--skip-unchanged", is_flag=True, help="Skip unchanged items when rebuilding restore operations.")
@pass_app
def snapshot_restore(
    app: AppContext,
    snapshot_file: Path,
    restore_names: bool,
    restore_folders: bool,
    bridge_timeout: float,
    queue_only: bool,
    skip_unchanged: bool,
) -> None:
    document = _load_snapshot(snapshot_file)
    snapshot_items = list(document.get("items") or [])
    item_ids = tuple(str(item.get("id")) for item in snapshot_items if str(item.get("id")))
    current_items = _collect_target_items(
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

    if app.dry_run:
        _emit_and_remember(
            app,
            "snapshot restore",
            {
                "status": "dry-run",
                "data": {
                    "snapshot_file": str(snapshot_file),
                    "metadata_operations": metadata_operations,
                    "rename_operations": rename_operations,
                    "move_operations": move_operations,
                    "skipped": skipped,
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
                "restored_metadata_count": len(metadata_results),
                "rename_operation_count": len(rename_operations),
                "move_operation_count": len(move_operations),
                "skipped": skipped,
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
    resolved_format = _write_items_export(output_file, query["items"], export_format)
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
@click.option("--strip", "strip_names", is_flag=True, help="Trim leading and trailing whitespace before applying prefix/suffix.")
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-snapshot", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Save a rollback snapshot before renaming.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def item_rename_bulk(
    app: AppContext,
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
    prefix: str,
    suffix: str,
    replace_from: str | None,
    replace_to: str,
    strip_names: bool,
    skip_unchanged: bool,
    save_snapshot: Path | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    items = _collect_target_items(
        app,
        item_ids=item_ids,
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
    if save_snapshot is not None:
        _write_snapshot(save_snapshot, _snapshot_document("item rename-bulk", items))
    operations, skipped = _build_rename_operations(
        items,
        prefix=prefix,
        suffix=suffix,
        replace_from=replace_from,
        replace_to=replace_to,
        strip_names=strip_names,
        skip_unchanged=skip_unchanged,
    )
    if app.dry_run:
        _emit_and_remember(
            app,
            "item rename-bulk",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": len(items),
                    "operation_count": len(operations),
                    "operations": operations,
                    "skipped": skipped,
                    "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
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
                "matched_count": len(items),
                "operation_count": len(operations),
                "operations": operations,
                "skipped": skipped,
                "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
                "bridge": bridge_result,
            },
        },
    )


@item.command("move-bulk")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to move.")
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
@click.option("--skip-unchanged", is_flag=True)
@click.option("--save-snapshot", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Save a rollback snapshot before moving.")
@click.option("--bridge-timeout", type=float, default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--queue-only", is_flag=True, help="Queue the bridge request without waiting for Eagle to process it.")
@pass_app
def item_move_bulk(
    app: AppContext,
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
    target_folder_id: str | None,
    target_folder_name: str | None,
    target_folder_path: str | None,
    ensure_target_path: str | None,
    skip_unchanged: bool,
    save_snapshot: Path | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    items = _collect_target_items(
        app,
        item_ids=item_ids,
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
    if app.dry_run:
        _emit_and_remember(
            app,
            "item move-bulk",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": len(items),
                    "operation_count": len(operations),
                    "target_folder": _folder_row(folder) if folder is not None else None,
                    "ensure_result": ensure_result,
                    "operations": operations,
                    "skipped": skipped,
                    "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
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
                "matched_count": len(items),
                "operation_count": len(operations),
                "target_folder": _folder_row(folder) if folder is not None else None,
                "ensure_result": ensure_result,
                "operations": operations,
                "skipped": skipped,
                "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
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
    items = [
        {
            "path": str(path),
            "name": path.stem,
            **({"website": website} if website else {}),
            **({"tags": list(tags)} if tags else {}),
            **({"annotation": annotation} if annotation else {}),
        }
        for path in files
    ]
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
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--mode", "modes", multiple=True, type=click.Choice(["name", "url", "name-size", "name-ext"]), help="Repeatable duplicate strategy.")
@click.option("--top", type=click.IntRange(1, None), default=10, show_default=True)
@click.option("--save-report", type=click.Path(dir_okay=False, path_type=Path), default=None)
@item_filter_options
@pass_app
def audit_duplicates(
    app: AppContext,
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
        item_ids=(),
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
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
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all matching items by paging with the current limit as page size.")
@click.option("--sample-limit", type=click.IntRange(1, None), default=10, show_default=True)
@click.option("--save-report", type=click.Path(dir_okay=False, path_type=Path), default=None)
@item_filter_options
@pass_app
def audit_cleanup(
    app: AppContext,
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
        item_ids=(),
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
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


@cli.group()
def organize() -> None:
    """Higher-level organization workflows."""


@organize.command("apply")
@click.option("--item-id", "item_ids", multiple=True, help="Explicit item IDs to organize.")
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
@click.option("--strip", "strip_names", is_flag=True)
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
    strip_names: bool,
    skip_unchanged: bool,
    save_snapshot: Path | None,
    save_matches: Path | None,
    save_plan: Path | None,
    bridge_timeout: float,
    queue_only: bool,
) -> None:
    _validate_item_selector_request(
        item_ids=item_ids,
        fetch_all=fetch_all,
        keyword=keyword,
        ext=ext,
        tags=tags,
        folders=folders,
        folder_names=folder_names,
        folder_paths=folder_paths,
    )
    items = _collect_target_items(
        app,
        item_ids=item_ids,
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
            max_items=None,
            require_match=None,
            skip_unchanged=skip_unchanged,
            save_matches=save_matches,
            save_plan=save_plan,
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
            strip_names=strip_names,
            skip_unchanged=skip_unchanged,
        )

    if app.dry_run:
        _emit_and_remember(
            app,
            "organize apply",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": len(items),
                    "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
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
                "matched_count": len(items),
                "saved_snapshot": str(save_snapshot) if save_snapshot is not None else None,
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
@pass_app
def plan_apply(app: AppContext, plan_file: Path) -> None:
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    operations = _extract_operations_from_document(data)
    if not operations:
        raise click.ClickException("No operations found in the plan file.")
    if app.dry_run:
        _emit_and_remember(
            app,
            "plan apply",
            {
                "status": "dry-run",
                "data": {
                    "plan_file": str(plan_file),
                    "operations": operations,
                },
            },
        )
        return

    results = []
    for operation in operations:
        response = app.client.raw_request(
            operation.get("method", "POST"),
            operation["endpoint"],
            payload=operation.get("payload"),
        )
        results.append(
            {
                "endpoint": operation["endpoint"],
                "method": operation.get("method", "POST"),
                "status": response.get("status", "success"),
                "description": operation.get("description"),
            }
        )

    _emit_and_remember(
        app,
        "plan apply",
        {
            "status": "success",
            "data": {
                "plan_file": str(plan_file),
                "applied_count": len(results),
                "results": results,
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


def _bulk_update_result(
    app: AppContext,
    *,
    item_ids: tuple[str, ...],
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

    source_items = _collect_target_items(
        app,
        item_ids=item_ids,
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
    matched_count = len(source_items)
    if require_match is not None and matched_count < require_match:
        raise click.ClickException(f"Matched {matched_count} item(s), which is below the required minimum of {require_match}.")
    if max_items is not None and matched_count > max_items:
        raise click.ClickException(f"Matched {matched_count} item(s), which exceeds --max-items {max_items}.")
    if save_matches is not None:
        _write_items_export(save_matches, source_items, "auto")

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
                    "item_ids": list(item_ids),
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
    if item_ids and any([keyword, ext, tags, folders, folder_names, folder_paths]):
        raise click.ClickException("Use either explicit --item-id values or filters, not both.")
    if not item_ids and not any([keyword, ext, tags, folders, folder_names, folder_paths]):
        raise click.ClickException("Refusing to bulk-update without item IDs or at least one filter.")


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
    fetch_all: bool,
    keyword: str | None,
    ext: str | None,
    tags: tuple[str, ...],
    folders: tuple[str, ...],
    folder_names: tuple[str, ...],
    folder_paths: tuple[str, ...],
) -> None:
    if item_ids and any([keyword, ext, tags, folders, folder_names, folder_paths]):
        raise click.ClickException("Use either explicit --item-id values or filters, not both.")
    if not item_ids and not fetch_all and not any([keyword, ext, tags, folders, folder_names, folder_paths]):
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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
        status = load_bridge_status()
        detail = ""
        if status is not None:
            detail = f" Last bridge heartbeat: {status.get('updatedAt', 'unknown')}."
        raise click.ClickException(
            f"Timed out waiting for the Eagle bridge plugin to process '{action}'. "
            f"Use `bridge status` and `bridge install-plugin` if needed.{detail}"
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
    strip_names: bool,
    skip_unchanged: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not any([prefix, suffix, replace_from is not None, strip_names]):
        raise click.ClickException("Provide at least one rename transform such as --prefix, --suffix, --replace-from, or --strip.")
    operations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in items:
        current_name = str(item.get("name") or "")
        next_name = current_name
        if replace_from is not None:
            next_name = next_name.replace(replace_from, replace_to or "")
        if strip_names:
            next_name = next_name.strip()
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


def _write_items_export(path: Path, items: list[dict[str, Any]], requested_format: str) -> str:
    export_format = _infer_export_format(path, requested_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    if export_format == "json":
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return export_format
    if export_format == "jsonl":
        lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items]
        text = "\n".join(lines)
        if lines:
            text += "\n"
        path.write_text(text, encoding="utf-8")
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


def _plan_document(command_name: str, operations: list[dict[str, Any]], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "eagle-cli-plan",
        "version": 1,
        "command": command_name,
        "context": context or {},
        "operations": operations,
    }


def _write_plan(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_manifest(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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
