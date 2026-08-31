"""Install toolchain dependencies for the real-tool registry (T-U4).

Installer is registry-driven: every install command comes from
``data/toolchain.yaml`` with a pinned version (no @latest — the reNgine
lesson). GOPROXY fallback and the GOPATH/bin tool path registration are
retained; sqlmap's pip branch migrated into the registry; ``dry_run`` stays
for offline tests.
"""
import os
import re
import shutil
import subprocess

from lattice_ai import toolchain_registry as tcr
from lattice_ai.tools import add_tool_path, find_real_executable

REQUIRED_VULN_TOOLS = ["nuclei", "sqlmap", "dalfox"]  # legacy: marketplace requires list

_GO_PROXY = "https://goproxy.cn,direct"


def _go_env() -> dict:
    env = {**os.environ}
    proxy = env.get("GOPROXY", "")
    if not proxy or "proxy.golang.org" in proxy:
        env["GOPROXY"] = _GO_PROXY
    return env


def _go_bin_dir() -> str:
    try:
        out = subprocess.run(["go", "env", "GOPATH"], capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip() + r"\bin"
    except Exception:
        pass
    return ""


def go_bin_dir() -> str:
    """Public helper so the server can register go-installed tools at startup."""
    return _go_bin_dir()


def _pip_command(primary: str) -> list[str] | None:
    """Resolve a pip-style install command against this interpreter."""
    parts = primary.split()
    python = shutil.which("python") or shutil.which("python3")
    if parts[0] == "python":
        if not python:
            return None
        return [python, *parts[1:]]
    # "pip install ..." -> prefer "<python> -m pip ..." for the right env
    if python:
        return [python, "-m", "pip", *parts[1:]]
    pip = shutil.which("pip")
    if not pip:
        return None
    return [pip, *parts[1:]]


def _install_one(name: str, *, dry_run: bool, allow_latest: bool = False) -> dict:
    entry = tcr.get_entry(name)
    exe = find_real_executable(name)
    if exe:
        return {
            "name": name,
            "status": "already_installed",
            "detail": f"found in PATH: {exe}",
            "version": tcr.registry_version(entry) if entry else None,
        }
    if entry is None:
        return {"name": name, "status": "skipped", "detail": "not in toolchain registry"}
    if not entry.install_primary:
        return {"name": name, "status": "manual", "detail": entry.install_manual or "manual install required"}

    primary = entry.install_primary
    if allow_latest and primary.startswith("go install "):
        primary = re.sub(r"@v[\w.\-]+$", "@latest", primary)

    if primary.startswith("go install "):
        package = primary[len("go install "):]
        go = shutil.which("go")
        if not go:
            return {"name": name, "status": "failed", "detail": "go not found; install Go first"}
        if dry_run:
            return {"name": name, "status": "installed", "detail": f"would run: go install {package}"}
        try:
            proc = subprocess.run(["go", "install", package], capture_output=True, text=True, timeout=600, env=_go_env())
        except Exception as exc:
            return {"name": name, "status": "failed", "detail": str(exc)}
        if proc.returncode != 0:
            return {"name": name, "status": "failed", "detail": proc.stderr.strip() or "go install failed"}
        add_tool_path(_go_bin_dir())
        return {"name": name, "status": "installed", "detail": "installed", "version": tcr.registry_version(entry)}

    if primary.startswith(("pip install ", "python -m pip install ")):
        cmd = _pip_command(primary)
        if cmd is None:
            return {"name": name, "status": "failed", "detail": "python/pip not found; install Python first"}
        if dry_run:
            return {"name": name, "status": "installed", "detail": "would run: " + " ".join(cmd)}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"name": name, "status": "failed", "detail": str(exc)}
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "pip install failed"
            return {"name": name, "status": "failed", "detail": detail[:500]}
        return {"name": name, "status": "installed", "detail": "installed", "version": tcr.registry_version(entry)}

    return {"name": name, "status": "skipped", "detail": f"unsupported install command: {primary}"}


def install_toolchain(names: list[str], *, dry_run: bool = False, on_progress=None,
                      allow_latest: bool = False) -> list[dict]:
    results = []
    for name in names:
        result = _install_one(name, dry_run=dry_run, allow_latest=allow_latest)
        results.append(result)
        if on_progress:
            on_progress(result)
    return results
