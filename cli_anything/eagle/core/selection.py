from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli_anything.eagle.core.files import atomic_write_json


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def safe_selection_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in name.strip())
    return cleaned or "selection"


def selection_dir(*, state_dir: Path) -> Path:
    path = state_dir / "selections"
    path.mkdir(parents=True, exist_ok=True)
    return path


def selection_path(name: str, *, state_dir: Path) -> Path:
    return selection_dir(state_dir=state_dir) / f"{safe_selection_name(name)}.json"


def selection_document(name: str, item_ids: list[str], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    unique_ids = _unique_preserve_order([str(item_id) for item_id in item_ids if str(item_id)])
    return {
        "kind": "eagle-cli-selection",
        "version": 1,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "item_ids": unique_ids,
        "item_count": len(unique_ids),
        "sample_ids": unique_ids[:10],
        "context": context or {},
    }


def save_selection_document(
    name: str,
    item_ids: list[str],
    *,
    state_dir: Path,
    context: dict[str, Any] | None = None,
) -> Path:
    path = selection_path(name, state_dir=state_dir)
    atomic_write_json(path, selection_document(name, item_ids, context=context))
    return path


def load_selection_document(name: str, *, state_dir: Path) -> dict[str, Any]:
    path = selection_path(name, state_dir=state_dir)
    if not path.exists():
        raise FileNotFoundError(name)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Selection document at {path} is not an object.")
    return payload


def list_selection_documents(*, state_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(selection_dir(state_dir=state_dir).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(
            {
                "name": payload.get("name") or path.stem,
                "path": str(path),
                "item_count": payload.get("item_count", len(payload.get("item_ids") or [])),
                "created_at": payload.get("created_at"),
            }
        )
    return rows


def delete_selection_document(name: str, *, state_dir: Path) -> bool:
    path = selection_path(name, state_dir=state_dir)
    if not path.exists():
        return False
    path.unlink()
    return True
