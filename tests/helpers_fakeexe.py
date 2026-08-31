"""Shared helper for tests that need a fake CLI tool on PATH.

Writes a Windows batch (or shell) script that responds to the registry's
version probe (``-V`` style flag) and then emits an arbitrary payload, so
tier/identity/parse tests can exercise the real CLI path offline.

``version_line=None`` makes the identity probe fail — simulating a PATH
name-collision binary that is not the real tool.
"""
import os
import stat
from pathlib import Path


def make_fake_exe(
    directory: Path,
    name: str,
    *,
    version_flag: str | None,
    version_line: str | None,
    payload: str,
    payload_stderr: str = "",
) -> Path:
    if os.name == "nt":
        exe = directory / f"{name}.bat"
        lines = ["@echo off"]
        if version_flag and version_line is not None:
            lines.append(f'IF "%1"=="{version_flag}" ECHO {version_line}')
        lines.append(f"ECHO {payload}")
        if payload_stderr:
            lines.append(f"ECHO {payload_stderr} 1>&2")
        exe.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    else:
        exe = directory / name
        body = "#!/bin/sh\n"
        if version_flag and version_line is not None:
            body += 'if [ "$1" = "%s" ]; then echo "%s"; exit 0; fi\n' % (version_flag, version_line)
        body += 'echo "%s"\n' % payload
        if payload_stderr:
            body += 'echo "%s" 1>&2\n' % payload_stderr
        exe.write_text(body, encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def version_flag_of(version_cmd: list[str]) -> str | None:
    """tools.py runs [exe] + version_cmd[1:] for identity checks, i.e. it
    drops the binary name and keeps the flags; the fake exe matches on the
    first flag. ``waybackurls`` has no real version flag — its regex matches
    the help header, so the flag is its -h."""
    return version_cmd[1] if len(version_cmd) > 1 else None
