import subprocess
from pathlib import Path

import pytest
from lattice_ai import toolchain_registry as tcr
from lattice_ai.tools import ToolRegistry

EXPECTED_NAMES = {
    "subfinder", "httpx", "naabu", "nmap", "dnsx", "tlsx",
    "katana", "gau", "waybackurls", "ffuf", "nuclei", "dalfox",
    "sqlmap",  # pip branch migrated into the registry (task D)
    "trivy",  # repo-audit dependency scanner (M2-A T0)
}


@pytest.fixture(autouse=True)
def _clear_version_cache():
    tcr._version_cache.clear()
    yield
    tcr._version_cache.clear()


def test_load_registry_has_the_twelve_tools():
    entries = tcr.load_registry()
    assert {e.name for e in entries} == EXPECTED_NAMES
    assert len(entries) == 14


def test_every_entry_is_pinned_and_wellformed():
    for e in tcr.load_registry():
        assert all(isinstance(p, str) and p for p in e.command)
        assert e.output_format in ("jsonl", "json", "xml", "text")
        assert e.parse_level in ("L1", "L2", "L3")
        assert e.danger in ("passive", "active", "aggressive")
        assert "{}" not in " ".join(e.command), "literal {} breaks str.format expansion"
        if e.install_primary:
            assert "@latest" not in e.install_primary
        for part in e.command:
            placeholders = set(__import__("re").findall(r"\{(\w+)\}", part))
            assert placeholders <= {"target"}, f"{e.name}: non-whitelisted placeholder {placeholders}"


def test_ffuf_wordlist_resolved_to_bundled_file():
    entry = tcr.get_entry("ffuf")
    assert entry is not None
    assert "{wordlist}" not in " ".join(entry.command)
    wordlist = Path(entry.command[entry.command.index("-w") + 1])
    assert wordlist.is_file() and wordlist.stat().st_size > 0


def test_missing_required_field_raises(tmp_path, monkeypatch):
    bad = tmp_path / "toolchain.yaml"
    bad.write_text("- name: only-name\n  category: x\n", encoding="utf-8")
    monkeypatch.setattr(tcr, "DATA_FILE", bad)
    with pytest.raises(tcr.RegistryError):
        tcr.load_registry()


def test_latest_is_rejected(tmp_path, monkeypatch):
    bad = tmp_path / "toolchain.yaml"
    bad.write_text(
        "- name: x\n  category: c\n  output_format: jsonl\n  parse_level: L1\n"
        "  command: ['x', '{target}']\n  install:\n    primary: 'go install foo@latest'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tcr, "DATA_FILE", bad)
    with pytest.raises(tcr.RegistryError):
        tcr.load_registry()


def test_duplicate_names_raise(tmp_path, monkeypatch):
    dup = tmp_path / "toolchain.yaml"
    entry = (
        "- name: x\n  category: c\n  output_format: jsonl\n  parse_level: L1\n"
        "  command: ['x', '{target}']\n"
    )
    dup.write_text(entry + entry, encoding="utf-8")
    monkeypatch.setattr(tcr, "DATA_FILE", dup)
    with pytest.raises(tcr.RegistryError):
        tcr.load_registry()


def test_injection_registers_cli_tools_and_keeps_sim_fallback():
    registry = ToolRegistry()
    from lattice_ai.builtins import install_builtins

    install_builtins(registry)
    tool = registry.get("subfinder")
    assert tool.runner == "cli"
    assert "-json" in tool.command
    # same-name sim remains available for the missing-executable fallback
    assert "subfinder" in registry._builtins


def test_install_builtins_includes_registry_tools():
    registry = ToolRegistry()
    from lattice_ai.builtins import install_builtins

    install_builtins(registry)
    for name in EXPECTED_NAMES:
        tool = registry.get(name)
        if name in ("tlsx", "gau", "waybackurls", "trivy"):
            assert tool.runner == "cli"  # no sim fallback: registry entry is the only one
        else:
            assert tool.runner == "cli"
            assert name in registry._builtins


def test_version_probe_uses_regex_and_caches(monkeypatch):
    entry = tcr.get_entry("subfinder")
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout="Current Version: v2.6.7\n", stderr="")

    monkeypatch.setattr(tcr.subprocess, "run", fake_run)
    assert tcr.registry_version(entry) == "2.6.7"
    assert tcr.registry_version(entry) == "2.6.7"
    assert calls["n"] == 1  # served from the 5s TTL cache


def test_version_probe_failure_is_none(monkeypatch):
    entry = tcr.get_entry("subfinder")

    def boom(cmd, **kwargs):
        raise FileNotFoundError("not installed")

    monkeypatch.setattr(tcr.subprocess, "run", boom)
    assert tcr.registry_version(entry) is None


def test_registry_view_shape(monkeypatch):
    monkeypatch.setattr("lattice_ai.tools.find_executable", lambda name: None)
    view = tcr.registry_view()
    by_name = {item["name"]: item for item in view}
    subfinder = by_name["subfinder"]
    assert subfinder["installed"] is False
    assert subfinder["version"] is None
    assert subfinder["install_mode"] == "auto"
    nmap = by_name["nmap"]
    assert nmap["install_mode"] == "manual"
    assert "nmap.org" in nmap["install_manual"]


def test_av_sensitive_tools_never_probe(monkeypatch):
    entry = tcr.get_entry("sqlmap")
    assert entry.av_sensitive is True

    def forbidden(cmd, **kwargs):
        raise AssertionError("av-sensitive tool must not be executed")

    monkeypatch.setattr(tcr.subprocess, "run", forbidden)
    assert tcr.registry_version(entry) is None
