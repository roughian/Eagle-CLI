from __future__ import annotations

import json
import os
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
HEALTHY_HEARTBEAT_SECONDS = 5.0
STALE_HEARTBEAT_SECONDS = 30.0


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


def _read_json_document(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    except OSError as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return {"value": payload}, None
    return payload, None


def wait_for_bridge_response(request_id: str, *, timeout_seconds: float = DEFAULT_WAIT_SECONDS, root: Path | None = None) -> dict[str, Any] | None:
    layout = ensure_bridge_dirs(root)
    response_path = layout["responses"] / f"{request_id}.json"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        if response_path.exists():
            payload, error = _read_json_document(response_path)
            if payload is not None:
                return payload
            if error is None:
                return None
        time.sleep(0.25)
    return None


def load_bridge_status(root: Path | None = None) -> dict[str, Any] | None:
    layout = ensure_bridge_dirs(root)
    status_path = layout["status"]
    payload, _error = _read_json_document(status_path)
    return payload


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_age_seconds(value: Any, *, now: datetime | None = None) -> float | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - parsed).total_seconds())


def file_age_seconds(path: Path, *, now: float | None = None) -> float | None:
    try:
        modified = path.stat().st_mtime
    except OSError:
        return None
    current = time.time() if now is None else now
    return max(0.0, current - modified)


def bridge_file_paths(kind: str, *, root: Path | None = None) -> list[Path]:
    layout = ensure_bridge_dirs(root)
    directory = layout[kind]
    files = [path for path in directory.glob("*.json") if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
    return files


def bridge_health(root: Path | None = None) -> dict[str, Any]:
    layout = ensure_bridge_dirs(root)
    status_path = layout["status"]
    status_payload, status_error = _read_json_document(status_path)
    request_files = bridge_file_paths("requests", root=root)
    response_files = bridge_file_paths("responses", root=root)
    processed_files = bridge_file_paths("processed", root=root)
    heartbeat_age = _timestamp_age_seconds((status_payload or {}).get("updatedAt"))
    if status_error is not None:
        health = "invalid"
    elif heartbeat_age is None:
        health = "offline"
    elif heartbeat_age <= HEALTHY_HEARTBEAT_SECONDS:
        health = "healthy"
    elif heartbeat_age <= STALE_HEARTBEAT_SECONDS:
        health = "stale"
    else:
        health = "offline"
    if request_files and health in {"stale", "offline"}:
        health = "stuck_queue"
    template_dir = companion_plugin_template_dir()
    installed = installed_plugin_paths()
    return {
        "health": health,
        "layout": {key: str(path) for key, path in layout.items()},
        "template_dir": str(template_dir),
        "template_exists": template_dir.exists(),
        "installed_plugin_paths": [str(path) for path in installed],
        "default_plugin_dirs": [str(path) for path in default_plugin_dir_candidates()],
        "status_path": str(status_path),
        "status_exists": status_path.exists(),
        "status_error": status_error,
        "status": status_payload,
        "heartbeat_age_seconds": heartbeat_age,
        "plugin_version": (status_payload or {}).get("pluginVersion"),
        "pending_request_count": len(request_files),
        "pending_response_count": len(response_files),
        "processed_count": len(processed_files),
        "queue_depth": len(request_files) + len(response_files),
        "writable": {
            key: os.access(path, os.W_OK)
            for key, path in {
                "state_dir": layout["state_dir"],
                "requests": layout["requests"],
                "responses": layout["responses"],
                "processed": layout["processed"],
            }.items()
        },
    }


def prune_bridge_files(
    *,
    root: Path | None = None,
    max_age_seconds: float,
    keep_last: int = 0,
    include_requests: bool = False,
    include_responses: bool = True,
    include_processed: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    selected = {
        "requests": include_requests,
        "responses": include_responses,
        "processed": include_processed,
    }
    result: dict[str, Any] = {
        "max_age_seconds": max_age_seconds,
        "keep_last": keep_last,
        "dry_run": dry_run,
        "groups": {},
        "candidate_count": 0,
        "deleted_count": 0,
    }
    for kind, enabled in selected.items():
        if not enabled:
            continue
        files = bridge_file_paths(kind, root=root)
        candidates = []
        protected = files[:keep_last] if keep_last > 0 else []
        for path in files:
            if path in protected:
                continue
            age_seconds = file_age_seconds(path)
            if age_seconds is None or age_seconds < max_age_seconds:
                continue
            candidate = {
                "path": str(path),
                "age_seconds": age_seconds,
                "deleted": False,
            }
            if not dry_run:
                path.unlink(missing_ok=True)
                candidate["deleted"] = True
                result["deleted_count"] += 1
            candidates.append(candidate)
        result["groups"][kind] = {
            "examined_count": len(files),
            "kept_count": len(files) - len(candidates),
            "candidates": candidates,
        }
        result["candidate_count"] += len(candidates)
    return result


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def companion_plugin_template_dir() -> Path:
    return repo_root() / "companion-plugin"


def export_companion_plugin(destination: Path) -> Path:
    # Import shutil lazily so routine bridge reads do not pay for optional
    # compression backends during module import.
    import shutil

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
