from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import click

from cli_anything.eagle.core.client import DEFAULT_BASE_URL, EagleApiError, EagleClient
from cli_anything.eagle.core.state import SessionState
from cli_anything.eagle.utils.output import emit, render_folder_tree
from cli_anything.eagle.utils.repl import start_repl


@dataclass
class AppContext:
    client: EagleClient
    state: SessionState
    json_output: bool
    timeout: float
    base_url: str


def pass_app(fn):
    return click.pass_obj(fn)


@click.group(invoke_without_command=True)
@click.option("--base-url", default=None, help="Eagle API base URL.")
@click.option("--timeout", default=None, type=float, help="HTTP timeout in seconds.")
@click.option("--json", "json_output", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def cli(ctx: click.Context, base_url: str | None, timeout: float | None, json_output: bool) -> None:
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
    )

    if ctx.invoked_subcommand is None:
        base_args: list[str] = []
        if resolved_base_url != DEFAULT_BASE_URL:
            base_args.extend(["--base-url", resolved_base_url])
        if resolved_timeout != 15.0:
            base_args.extend(["--timeout", str(resolved_timeout)])
        if json_output:
            base_args.append("--json")
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
    _emit_and_remember(app, "library switch", app.client.library_switch(library_path))


@library.command("icon")
@click.argument("library_path", type=click.Path())
@click.option("--download", type=click.Path(dir_okay=False, path_type=Path), help="Save the icon to a file.")
@pass_app
def library_icon(app: AppContext, library_path: str, download: Path | None) -> None:
    if download is not None:
        saved = app.client.library_icon_download(library_path, str(download))
        _emit_and_remember(app, "library icon", {"saved_to": saved})
        return
    _emit_and_remember(app, "library icon", {"url": app.client.library_icon_url(library_path)})


@cli.group()
def folder() -> None:
    """Folder commands."""


@folder.command("list")
@pass_app
def folder_list(app: AppContext) -> None:
    _emit_and_remember(app, "folder list", app.client.folder_list())


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


@folder.command("recent")
@pass_app
def folder_recent(app: AppContext) -> None:
    _emit_and_remember(app, "folder recent", app.client.folder_recent())


@folder.command("create")
@click.argument("folder_name")
@click.option("--parent", help="Parent folder ID.")
@pass_app
def folder_create(app: AppContext, folder_name: str, parent: str | None) -> None:
    _emit_and_remember(app, "folder create", app.client.folder_create(folder_name, parent=parent))


@folder.command("rename")
@click.argument("folder_id")
@click.argument("new_name")
@pass_app
def folder_rename(app: AppContext, folder_id: str, new_name: str) -> None:
    _emit_and_remember(app, "folder rename", app.client.folder_rename(folder_id, new_name))


@folder.command("update")
@click.argument("folder_id")
@click.option("--name", "new_name", help="New folder name.")
@click.option("--description", "new_description", help="New folder description.")
@click.option(
    "--color",
    "new_color",
    type=click.Choice(["red", "orange", "green", "yellow", "aqua", "blue", "purple", "pink"]),
    help="New folder color.",
)
@pass_app
def folder_update(
    app: AppContext,
    folder_id: str,
    new_name: str | None,
    new_description: str | None,
    new_color: str | None,
) -> None:
    _emit_and_remember(
        app,
        "folder update",
        app.client.folder_update(
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
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--order-by", default=None, help="Examples: CREATEDATE, -FILESIZE, NAME, -RESOLUTION.")
@click.option("--keyword", default=None)
@click.option("--ext", default=None)
@click.option("--tag", "tags", multiple=True, help="Repeatable tag filter.")
@click.option("--folder", "folders", multiple=True, help="Repeatable folder ID filter.")
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
) -> None:
    params = {
        "limit": limit,
        "offset": offset,
        "orderBy": order_by,
        "keyword": keyword,
        "ext": ext,
        "tags": ",".join(tags) if tags else None,
        "folders": ",".join(folders) if folders else None,
    }
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
    _emit_and_remember(
        app,
        "item update",
        app.client.item_update(
            item_id,
            tags=list(tags) if tags else None,
            annotation=annotation,
            url=source_url,
            star=star,
        ),
    )


@item.command("add-path")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--name", default=None, help="Defaults to the file stem.")
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--folder-id", default=None)
@pass_app
def item_add_path(
    app: AppContext,
    path: str,
    name: str | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    folder_id: str | None,
) -> None:
    resolved_name = name or Path(path).stem
    _emit_and_remember(
        app,
        "item add-path",
        app.client.item_add_from_path(
            path,
            name=resolved_name,
            website=website,
            tags=list(tags) if tags else None,
            annotation=annotation,
            folder_id=folder_id,
        ),
    )


@item.command("add-paths")
@click.option("--path", "paths", multiple=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--folder-id", default=None)
@pass_app
def item_add_paths(
    app: AppContext,
    paths: tuple[str, ...],
    manifest: str | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    folder_id: str | None,
) -> None:
    items = _load_batch_items_from_paths(paths, manifest, website=website, tags=list(tags), annotation=annotation)
    _emit_and_remember(app, "item add-paths", app.client.item_add_from_paths(items, folder_id=folder_id))


@item.command("add-url")
@click.argument("url")
@click.option("--name", default=None, help="Defaults from the URL path.")
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--star", type=click.IntRange(0, 5), default=None)
@click.option("--annotation", default=None)
@click.option("--modification-time", type=int, default=None)
@click.option("--folder-id", default=None)
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
    headers_json: str | None,
) -> None:
    headers = json.loads(headers_json) if headers_json else None
    resolved_name = name or _derive_name_from_url(url)
    _emit_and_remember(
        app,
        "item add-url",
        app.client.item_add_from_url(
            url,
            name=resolved_name,
            website=website,
            tags=list(tags) if tags else None,
            star=star,
            annotation=annotation,
            modification_time=modification_time,
            folder_id=folder_id,
            headers=headers,
        ),
    )


@item.command("add-urls")
@click.option("--url", "urls", multiple=True)
@click.option("--manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--website", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--annotation", default=None)
@click.option("--folder-id", default=None)
@pass_app
def item_add_urls(
    app: AppContext,
    urls: tuple[str, ...],
    manifest: str | None,
    website: str | None,
    tags: tuple[str, ...],
    annotation: str | None,
    folder_id: str | None,
) -> None:
    items = _load_batch_items_from_urls(urls, manifest, website=website, tags=list(tags), annotation=annotation)
    _emit_and_remember(app, "item add-urls", app.client.item_add_from_urls(items, folder_id=folder_id))


@item.command("add-bookmark")
@click.argument("url")
@click.option("--name", default=None, help="Defaults from the URL path.")
@click.option("--base64-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--tag", "tags", multiple=True)
@click.option("--modification-time", type=int, default=None)
@click.option("--folder-id", default=None)
@pass_app
def item_add_bookmark(
    app: AppContext,
    url: str,
    name: str | None,
    base64_file: str | None,
    tags: tuple[str, ...],
    modification_time: int | None,
    folder_id: str | None,
) -> None:
    base64 = Path(base64_file).read_text(encoding="utf-8") if base64_file else None
    resolved_name = name or _derive_name_from_url(url)
    _emit_and_remember(
        app,
        "item add-bookmark",
        app.client.item_add_bookmark(
            url,
            name=resolved_name,
            base64=base64,
            tags=list(tags) if tags else None,
            modification_time=modification_time,
            folder_id=folder_id,
        ),
    )


@item.command("trash")
@click.argument("item_ids", nargs=-1, required=True)
@pass_app
def item_trash(app: AppContext, item_ids: tuple[str, ...]) -> None:
    _emit_and_remember(app, "item trash", app.client.item_move_to_trash(list(item_ids)))


@item.command("refresh-palette")
@click.argument("item_id")
@pass_app
def item_refresh_palette(app: AppContext, item_id: str) -> None:
    _emit_and_remember(app, "item refresh-palette", app.client.item_refresh_palette(item_id))


@item.command("refresh-thumbnail")
@click.argument("item_id")
@pass_app
def item_refresh_thumbnail(app: AppContext, item_id: str) -> None:
    _emit_and_remember(app, "item refresh-thumbnail", app.client.item_refresh_thumbnail(item_id))


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
    _emit_and_remember(app, "raw request", app.client.raw_request(method, path, params=params, payload=payload))


def _emit_and_remember(app: AppContext, command_name: str, response: dict) -> None:
    sanitized = _sanitize_output(response)
    app.state.base_url = app.base_url
    app.state.timeout = app.timeout
    app.state.record(command_name, sanitized)
    app.state.save()
    emit(sanitized, json_output=app.json_output)


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


def _sanitize_output(value):
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
