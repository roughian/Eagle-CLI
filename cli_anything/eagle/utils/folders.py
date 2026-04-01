from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FolderRecord:
    id: str
    name: str
    path: str
    depth: int
    parent_id: str | None
    parent_path: str | None
    raw: dict[str, Any]


def flatten_folders(
    folders: list[dict[str, Any]],
    *,
    parent_id: str | None = None,
    parent_path: str | None = None,
    depth: int = 0,
) -> list[FolderRecord]:
    records: list[FolderRecord] = []
    for folder in folders:
        name = str(folder.get("name", ""))
        path = f"{parent_path}/{name}" if parent_path else name
        record = FolderRecord(
            id=str(folder.get("id", "")),
            name=name,
            path=path,
            depth=depth,
            parent_id=parent_id,
            parent_path=parent_path,
            raw=folder,
        )
        records.append(record)
        children = folder.get("children") or []
        if isinstance(children, list):
            records.extend(
                flatten_folders(
                    children,
                    parent_id=record.id,
                    parent_path=record.path,
                    depth=depth + 1,
                )
            )
    return records


def find_folders_by_name(
    records: list[FolderRecord],
    query: str,
    *,
    exact: bool = False,
    parent_id: str | None = None,
) -> list[FolderRecord]:
    normalized = query.casefold()
    matches: list[FolderRecord] = []
    for record in records:
        if parent_id is not None and record.parent_id != parent_id:
            continue
        haystack = record.name.casefold()
        if exact and haystack == normalized:
            matches.append(record)
        elif not exact and normalized in haystack:
            matches.append(record)
    return matches


def find_folder_by_path(records: list[FolderRecord], path: str) -> FolderRecord | None:
    normalized = normalize_folder_path(path).casefold()
    for record in records:
        if record.path.casefold() == normalized:
            return record
    return None


def normalize_folder_path(path: str) -> str:
    segments = [segment.strip() for segment in path.split("/") if segment.strip()]
    return "/".join(segments)
