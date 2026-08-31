"""App-level preferences (theme, language)."""
import json
from pathlib import Path

from lattice_ai.persistence import atomic_write_json
from lattice_ai.paths import data_root

_DEFAULTS = {"theme": "light", "language": "en"}
_PREFS_FILE = data_root() / "preferences.json"

_THEMES = {"system", "light", "dark"}
_LANGUAGES = {"zh", "en"}


def load_preferences() -> dict:
    data = dict(_DEFAULTS)
    if _PREFS_FILE.exists():
        try:
            data.update(json.loads(_PREFS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return {k: data.get(k, _DEFAULTS[k]) for k in _DEFAULTS}


def save_preferences(patch: dict) -> dict:
    current = load_preferences()
    for key in ("theme", "language"):
        if key in patch and patch[key] is not None:
            current[key] = str(patch[key]).strip()
    if current["theme"] not in _THEMES:
        raise ValueError(f"invalid theme: {current['theme']}")
    if current["language"] not in _LANGUAGES:
        raise ValueError(f"invalid language: {current['language']}")
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_PREFS_FILE, current)
    return current
