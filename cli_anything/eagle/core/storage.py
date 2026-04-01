from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cli_anything.eagle.core.state import DEFAULT_STATE_DIR


PRESETS_PATH = DEFAULT_STATE_DIR / "presets.json"


def load_presets(path: Path | None = None) -> dict[str, Any]:
    preset_path = path or PRESETS_PATH
    if not preset_path.exists():
        return {"version": 1, "presets": {}}
    data = json.loads(preset_path.read_text(encoding="utf-8"))
    if "presets" not in data:
        data = {"version": 1, "presets": data}
    return data


def save_presets(data: dict[str, Any], path: Path | None = None) -> None:
    preset_path = path or PRESETS_PATH
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    preset_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def get_preset(name: str, path: Path | None = None) -> dict[str, Any] | None:
    data = load_presets(path)
    return data.get("presets", {}).get(name)


def set_preset(name: str, preset: dict[str, Any], path: Path | None = None) -> None:
    data = load_presets(path)
    data.setdefault("presets", {})[name] = preset
    save_presets(data, path)


def delete_preset(name: str, path: Path | None = None) -> bool:
    data = load_presets(path)
    presets = data.setdefault("presets", {})
    if name not in presets:
        return False
    del presets[name]
    save_presets(data, path)
    return True
