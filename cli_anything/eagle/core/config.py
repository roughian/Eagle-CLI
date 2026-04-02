from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cli_anything.eagle.core.files import atomic_write_json
from cli_anything.eagle.core.state import DEFAULT_STATE_DIR


DEFAULT_CONFIG_PATH = DEFAULT_STATE_DIR / "config.json"

_CONFIG_SPECS = {
    "base_url": {"type": "str"},
    "timeout": {"type": "float"},
    "report_format": {"type": "choice", "choices": {"auto", "json", "md", "html", "csv"}},
    "export_format": {"type": "choice", "choices": {"auto", "json", "jsonl", "csv"}},
    "completion_shell": {"type": "choice", "choices": {"bash", "zsh", "fish"}},
    "watch_state_file": {"type": "path"},
}


def config_path(path: Path | None = None) -> Path:
    return path or DEFAULT_CONFIG_PATH


def config_keys() -> list[str]:
    return sorted(_CONFIG_SPECS.keys())


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = config_path(path)
    if not target.exists():
        return {"version": 1, "defaults": {}}
    payload = json.loads(target.read_text(encoding="utf-8"))
    defaults = payload.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}
    return {
        "version": int(payload.get("version", 1)),
        "defaults": defaults,
    }


def save_config(data: dict[str, Any], path: Path | None = None) -> None:
    atomic_write_json(config_path(path), data)


def normalize_config_value(key: str, value: str) -> Any:
    if key not in _CONFIG_SPECS:
        raise KeyError(key)
    spec = _CONFIG_SPECS[key]
    kind = spec["type"]
    if kind == "str":
        return str(value)
    if kind == "float":
        return float(value)
    if kind == "path":
        return str(Path(value).expanduser())
    if kind == "choice":
        normalized = str(value)
        if normalized not in spec["choices"]:
            choices = ", ".join(sorted(spec["choices"]))
            raise ValueError(f"{key} must be one of: {choices}")
        return normalized
    raise ValueError(f"Unsupported config key: {key}")


def set_config_value(key: str, value: str, path: Path | None = None) -> Any:
    data = load_config(path)
    normalized = normalize_config_value(key, value)
    data.setdefault("defaults", {})[key] = normalized
    save_config(data, path)
    return normalized


def unset_config_value(key: str, path: Path | None = None) -> bool:
    data = load_config(path)
    defaults = data.setdefault("defaults", {})
    if key not in defaults:
        return False
    del defaults[key]
    save_config(data, path)
    return True
