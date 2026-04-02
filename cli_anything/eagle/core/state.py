from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cli_anything.eagle.core.files import atomic_write_json


DEFAULT_STATE_DIR = Path(
    os.environ.get(
        "EAGLE_AGENT_STATE_DIR",
        Path.home() / ".config" / "cli-anything-eagle",
    )
)
LEGACY_STATE_DIR = Path.home() / ".config" / "eagle-agent-harness"
DEFAULT_STATE_PATH = DEFAULT_STATE_DIR / "session.json"
LEGACY_STATE_PATH = LEGACY_STATE_DIR / "session.json"


@dataclass
class SessionState:
    base_url: str = "http://localhost:41595"
    timeout: float = 15.0
    api_variant: str | None = None
    last_command: str | None = None
    last_item_ids: list[str] = field(default_factory=list)
    last_folder_ids: list[str] = field(default_factory=list)
    last_response: Any = None

    @classmethod
    def load(cls, path: Path | None = None) -> "SessionState":
        state_path = _resolve_state_path(path)
        if not state_path.exists():
            return cls()
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt_path = state_path.with_name(f"{state_path.stem}.corrupt-{int(time.time())}{state_path.suffix}")
            try:
                state_path.replace(corrupt_path)
            except OSError:
                pass
            return cls()
        return cls(**data)

    def save(self, path: Path | None = None) -> None:
        state_path = path or DEFAULT_STATE_PATH
        atomic_write_json(state_path, asdict(self))

    def record(self, command_name: str, response: Any) -> None:
        self.last_command = command_name
        self.last_response = response
        self.last_item_ids = _collect_ids(response, "item")
        self.last_folder_ids = _collect_ids(response, "folder")


def _collect_ids(value: Any, kind: str) -> list[str]:
    ids: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node_id = node.get("id")
            if isinstance(node_id, str):
                is_folder = "children" in node or "imageCount" in node or "extendTags" in node
                is_item = "ext" in node or "isDeleted" in node or "palettes" in node
                if kind == "folder" and is_folder:
                    ids.append(node_id)
                elif kind == "item" and is_item:
                    ids.append(node_id)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    seen: list[str] = []
    for item_id in ids:
        if item_id not in seen:
            seen.append(item_id)
    return seen


def _resolve_state_path(path: Path | None) -> Path:
    if path is not None:
        return path
    if DEFAULT_STATE_PATH.exists():
        return DEFAULT_STATE_PATH
    if LEGACY_STATE_PATH.exists():
        return LEGACY_STATE_PATH
    return DEFAULT_STATE_PATH
