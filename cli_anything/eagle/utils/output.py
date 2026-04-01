from __future__ import annotations

import json
from typing import Any

import click


def emit(value: Any, *, json_output: bool = False, columns: list[str] | None = None) -> None:
    if json_output:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            click.echo(render_table(value, columns=columns))
            return
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return

    if isinstance(value, dict):
        if "data" in value and set(value.keys()) <= {"status", "data"}:
            emit(value["data"], json_output=json_output, columns=columns)
            return
        rows = [{"key": key, "value": _stringify(item)} for key, item in value.items()]
        click.echo(render_table(rows, columns=["key", "value"]))
        return

    click.echo(_stringify(value))


def render_table(rows: list[dict[str, Any]], *, columns: list[str] | None = None) -> str:
    if not rows:
        return "(no rows)"

    ordered_columns = columns or _collect_columns(rows)
    widths = {
        column: max(len(column), max(len(_stringify(row.get(column, ""))) for row in rows))
        for column in ordered_columns
    }
    header = "  ".join(column.ljust(widths[column]) for column in ordered_columns)
    divider = "  ".join("-" * widths[column] for column in ordered_columns)
    body = [
        "  ".join(_stringify(row.get(column, "")).ljust(widths[column]) for column in ordered_columns)
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def render_folder_tree(folders: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    def walk(nodes: list[dict[str, Any]], depth: int) -> None:
        prefix = "  " * depth
        for node in nodes:
            label = f"{prefix}- {node.get('name', '<unnamed>')} [{node.get('id', '')}]"
            lines.append(label)
            children = node.get("children") or []
            if isinstance(children, list):
                walk(children, depth + 1)

    walk(folders, 0)
    return "\n".join(lines) if lines else "(no folders)"


def _collect_columns(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in ordered:
                ordered.append(key)
    return ordered


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text) > 80:
            return text[:77] + "..."
        return text
    if value is None:
        return ""
    return str(value)
