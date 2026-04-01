from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click

from cli_anything.eagle import __version__
from cli_anything.eagle.core.client import DEFAULT_BASE_URL, EagleApiError, EagleClient
from cli_anything.eagle.core.state import SessionState
from cli_anything.eagle.core.storage import delete_preset, get_preset, load_presets, set_preset
from cli_anything.eagle.utils.folders import (
    FolderRecord,
    find_folder_by_path,
    find_folders_by_name,
    flatten_folders,
    normalize_folder_path,
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
        rows.append(
            {
                "name": name,
                "kind": preset_data.get("kind", ""),
                "keyword": params.get("keyword", ""),
                "tags": params.get("tags", []),
                "folders": params.get("folder_paths", []) or params.get("folder_names", []) or params.get("folders", []),
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
@item_filter_options
@pass_app
def item_list(
    app: AppContext,
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
    params = _build_item_filters(
        app,
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
    _emit_and_remember(app, "item list", app.client.item_list(**params))


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
    save_plan: Path | None,
) -> None:
    if not any([set_tags, add_tags, annotation is not None, source_url is not None, star is not None]):
        raise click.ClickException("Provide at least one mutation field such as --set-tag, --add-tag, --annotation, --url, or --star.")

    if item_ids and any([keyword, ext, tags, folders, folder_names, folder_paths]):
        raise click.ClickException("Use either explicit --item-id values or filters, not both.")

    if not item_ids and not any([keyword, ext, tags, folders, folder_names, folder_paths]):
        raise click.ClickException("Refusing to bulk-update without item IDs or at least one filter.")

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
    operations: list[dict[str, Any]] = []
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
                    "matched_count": len(operations),
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
                },
            ),
        )

    if app.dry_run:
        _emit_and_remember(
            app,
            "item bulk-update",
            {
                "status": "dry-run",
                "data": {
                    "matched_count": len(operations),
                    "operations": operations,
                    "saved_plan": str(save_plan) if save_plan is not None else None,
                },
            },
        )
        return

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

    _emit_and_remember(
        app,
        "item bulk-update",
        {
            "status": "success",
            "data": {
                "matched_count": len(operations),
                "updated_count": len(results),
                "items": results,
                "operations": operations,
                "saved_plan": str(save_plan) if save_plan is not None else None,
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


def _collect_target_items(
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
) -> list[dict[str, Any]]:
    if item_ids:
        return [app.client.item_info(item_id)["data"] for item_id in item_ids]
    filters = _build_item_filters(
        app,
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
    return list(app.client.item_list(**filters)["data"])


def _resolve_folder_filters(
    app: AppContext,
    *,
    folder_ids: list[str],
    folder_names: list[str],
    folder_paths: list[str],
) -> list[str]:
    if not any([folder_ids, folder_names, folder_paths]):
        return []
    records = _folder_records(app)
    resolved = list(folder_ids)
    for folder_id in folder_ids:
        if not any(record.id == folder_id for record in records):
            raise click.ClickException(f"Unknown folder ID: {folder_id}")
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


def _derive_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = Path(parsed.path).name
    return tail or parsed.netloc or "bookmark"


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
