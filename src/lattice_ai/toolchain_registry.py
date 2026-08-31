"""Toolchain registry (T-U1): metadata for the first batch of real CLI tools.

The registry is the distribution-maintained manifest of real tools — distinct
from the user-facing YAML recipes in the tool store. Loading it injects each
entry as a ``runner="cli"`` Tool into the ToolRegistry, which makes the
existing same-name builtin fallback (missing executable -> sim) work
automatically, and gives ToolsPage / the installer a single source of truth
for install commands, versions and parse hints.
"""
import json
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from lattice_ai.models import Tool

DATA_FILE = Path(__file__).resolve().parent / "data" / "toolchain.yaml"
WORDLIST_FILE = Path(__file__).resolve().parent / "data" / "wordlists" / "common.txt"

VALID_OUTPUT_FORMATS = ("jsonl", "json", "xml", "text")
VALID_PARSE_LEVELS = ("L1", "L2", "L3")
VALID_DANGER = ("passive", "active", "aggressive")

_VERSION_TTL = 5.0
_version_cache: dict[str, tuple[float, str | None]] = {}
_version_lock = threading.Lock()


class RegistryError(Exception):
    pass


@dataclass
class RegistryEntry:
    name: str
    category: str
    output_format: str
    parse_level: str
    command: list[str] = field(default_factory=list)
    install_primary: str = ""
    install_fallback: str = ""
    install_manual: str = ""
    version_cmd: list[str] = field(default_factory=list)
    version_regex: str = ""
    license: str = ""
    builtin_fallback: str = ""
    danger: str = "passive"
    platforms: dict[str, str] = field(default_factory=dict)
    av_sensitive: bool = False
    notes: str = ""


def _normalize_platforms(raw) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k).lower(): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return {str(k).lower(): "go" for k in raw}
    return {}


def _resolve_command(command: list[str]) -> list[str]:
    # {wordlist} is a bundled constant, not user input (doc §5.2 whitelist).
    return [part.replace("{wordlist}", str(WORDLIST_FILE)) for part in command]


def _entry_from_dict(raw: dict) -> RegistryEntry:
    for required in ("name", "category", "output_format", "parse_level", "command"):
        if not raw.get(required):
            raise RegistryError(f"toolchain.yaml entry missing required field {required!r}: {raw}")
    name = str(raw["name"])
    output_format = str(raw["output_format"])
    parse_level = str(raw["parse_level"])
    danger = str(raw.get("danger", "passive"))
    if output_format not in VALID_OUTPUT_FORMATS:
        raise RegistryError(f"{name}: invalid output_format {output_format!r}")
    if parse_level not in VALID_PARSE_LEVELS:
        raise RegistryError(f"{name}: invalid parse_level {parse_level!r}")
    if danger not in VALID_DANGER:
        raise RegistryError(f"{name}: invalid danger {danger!r}")
    install = raw.get("install") or {}
    if isinstance(install, str):
        install = {"primary": install}
    primary = str(install.get("primary", "") or "")
    if primary and "@latest" in primary:
        raise RegistryError(f"{name}: install.primary must pin a version (no @latest)")
    command = raw["command"]
    if not isinstance(command, list) or not all(isinstance(p, str) for p in command):
        raise RegistryError(f"{name}: command must be a list of strings")
    return RegistryEntry(
        name=name,
        category=str(raw["category"]),
        output_format=output_format,
        parse_level=parse_level,
        command=_resolve_command(command),
        install_primary=primary,
        install_fallback=str(install.get("fallback", "") or ""),
        install_manual=str(install.get("manual", "") or ""),
        version_cmd=[str(p) for p in (raw.get("version_cmd") or [])],
        version_regex=str(raw.get("version_regex", "") or ""),
        license=str(raw.get("license", "") or ""),
        builtin_fallback=str(raw.get("builtin_fallback", "") or ""),
        danger=danger,
        platforms=_normalize_platforms(raw.get("platforms")),
        av_sensitive=bool(raw.get("av_sensitive", False)),
        notes=str(raw.get("notes", "") or ""),
    )


def load_registry(refresh: bool = False) -> list[RegistryEntry]:
    """Load and validate the YAML manifest; empty list when the file is absent."""
    if not DATA_FILE.exists():
        return []
    data = yaml.safe_load(DATA_FILE.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise RegistryError("toolchain.yaml must be a list of tool entries")
    entries = [_entry_from_dict(item) for item in data]
    names = [e.name for e in entries]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise RegistryError(f"duplicate registry entries: {sorted(duplicates)}")
    return entries


def get_entry(name: str) -> RegistryEntry | None:
    for entry in load_registry():
        if entry.name == name:
            return entry
    return None


def registry_version(entry: RegistryEntry) -> str | None:
    """Probe the installed tool's version via version_cmd (5s TTL cache).

    Never raises: probe failures (missing exe, bad output, timeout) yield None.
    """
    if not entry.version_cmd or entry.av_sensitive:
        # av-sensitive tools (AV-flagged scripts, e.g. sqlmap) are never
        # auto-executed: probing would pop the user's antivirus every time.
        return None
    now = time.monotonic()
    with _version_lock:
        cached = _version_cache.get(entry.name)
        if cached and now - cached[0] < _VERSION_TTL:
            return cached[1]
    version = None
    try:
        # Resolve the binary the same way the execution layer does, so Windows
        # .BAT wrappers (pip sqlmap) resolve instead of failing CreateProcess.
        from lattice_ai.tools import find_executable

        exe = find_executable(entry.version_cmd[0])
        argv = [exe, *entry.version_cmd[1:]] if exe else list(entry.version_cmd)
        if exe and exe.lower().endswith((".bat", ".cmd")):
            argv = ["cmd", "/c", *argv]
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,  # some tools (sqlmap) prompt interactively
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if entry.version_regex:
            m = re.search(entry.version_regex, output)
            version = m.group(1) if m and m.groups() else (m.group(0) if m else None)
        elif proc.returncode == 0:
            version = output.strip().splitlines()[0][:40] if output.strip() else None
    except Exception:
        version = None
    with _version_lock:
        _version_cache[entry.name] = (time.monotonic(), version)
    return version


def install_registry_tools(registry) -> int:
    """Inject registry entries as runner="cli" Tools into a ToolRegistry.

    Called alongside install_builtins so the same-name builtin fallback works.
    Returns the number of tools registered.
    """
    count = 0
    for entry in load_registry():
        registry.register(
            Tool(
                name=entry.name,
                description=f"[registry] {entry.notes}"[:200],
                runner="cli",
                command=list(entry.command),
                category=entry.category,
                approval="allow",
            )
        )
        count += 1
    return count


def registry_view() -> list[dict]:
    """API shape for GET /api/toolchain/registry: entries + install state."""
    from lattice_ai.tools import find_real_executable

    out = []
    for entry in load_registry():
        installed = find_real_executable(entry.name) is not None
        item = asdict(entry)
        item["command"] = list(entry.command)
        item["installed"] = installed
        item["version"] = registry_version(entry) if installed else None
        manual = bool(entry.install_manual) and not entry.install_primary
        item["install_mode"] = "manual" if manual else ("none" if not entry.install_primary else "auto")
        out.append(item)
    return out
