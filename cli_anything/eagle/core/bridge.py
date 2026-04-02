from __future__ import annotations

import json
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli_anything.eagle.core.files import atomic_write_json
from cli_anything.eagle.core.state import DEFAULT_STATE_DIR


BRIDGE_PLUGIN_ID = "2f40db08-5ce8-4d72-9fb7-a8fdcb5c1f6b"
BRIDGE_PLUGIN_NAME = "CLI-Anything Eagle Bridge"
BRIDGE_STATE_DIR = DEFAULT_STATE_DIR / "bridge"
REQUESTS_DIR = BRIDGE_STATE_DIR / "requests"
RESPONSES_DIR = BRIDGE_STATE_DIR / "responses"
PROCESSED_DIR = BRIDGE_STATE_DIR / "processed"
STATUS_PATH = BRIDGE_STATE_DIR / "status.json"
DEFAULT_WAIT_SECONDS = 15.0


def bridge_layout(root: Path | None = None) -> dict[str, Path]:
    state_dir = root or BRIDGE_STATE_DIR
    return {
        "state_dir": state_dir,
        "requests": state_dir / "requests",
        "responses": state_dir / "responses",
        "processed": state_dir / "processed",
        "status": state_dir / "status.json",
    }


def ensure_bridge_dirs(root: Path | None = None) -> dict[str, Path]:
    layout = bridge_layout(root)
    for key in ["state_dir", "requests", "responses", "processed"]:
        layout[key].mkdir(parents=True, exist_ok=True)
    return layout


def write_bridge_request(action: str, payload: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    layout = ensure_bridge_dirs(root)
    request_id = str(uuid.uuid4())
    document = {
        "kind": "eagle-cli-bridge-request",
        "version": 1,
        "id": request_id,
        "action": action,
        "created_at": utc_now(),
        "payload": payload,
    }
    request_path = layout["requests"] / f"{request_id}.json"
    atomic_write_json(request_path, document)
    return {
        "request_id": request_id,
        "request_path": request_path,
        "response_path": layout["responses"] / f"{request_id}.json",
        "document": document,
    }


def wait_for_bridge_response(request_id: str, *, timeout_seconds: float = DEFAULT_WAIT_SECONDS, root: Path | None = None) -> dict[str, Any] | None:
    layout = ensure_bridge_dirs(root)
    response_path = layout["responses"] / f"{request_id}.json"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        if response_path.exists():
            return json.loads(response_path.read_text(encoding="utf-8"))
        time.sleep(0.25)
    return None


def load_bridge_status(root: Path | None = None) -> dict[str, Any] | None:
    layout = ensure_bridge_dirs(root)
    status_path = layout["status"]
    if not status_path.exists():
        return None
    return json.loads(status_path.read_text(encoding="utf-8"))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def companion_plugin_template_dir() -> Path:
    return repo_root() / "companion-plugin"


def export_companion_plugin(destination: Path) -> Path:
    source = companion_plugin_template_dir()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def install_companion_plugin(plugin_root: Path) -> Path:
    plugin_root.mkdir(parents=True, exist_ok=True)
    target = plugin_root / BRIDGE_PLUGIN_ID
    return export_companion_plugin(target)


def default_plugin_dir_candidates() -> list[Path]:
    return [
        Path.home() / "Library/Application Support/Eagle/plugins",
        Path.home() / "Library/Application Support/Eagle/Plugins",
    ]


def installed_plugin_paths(plugin_dirs: list[Path] | None = None) -> list[Path]:
    candidates = plugin_dirs or default_plugin_dir_candidates()
    found: list[Path] = []
    for root in candidates:
        target = root / BRIDGE_PLUGIN_ID
        if target.exists():
            found.append(target)
    return found


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
