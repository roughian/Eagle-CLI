from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_STATE_DIR = Path(
    os.environ.get(
        "EAGLE_AGENT_STATE_DIR",
        Path.home() / ".config" / "eagle-agent-harness",
    )
)
DEFAULT_STATE_PATH = DEFAULT_STATE_DIR / "session.json"


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
        state_path = path or DEFAULT_STATE_PATH
        if not state_path.exists():
            return cls()

        data = json.loads(state_path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path | None = None) -> None:
        state_path = path or DEFAULT_STATE_PATH
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
