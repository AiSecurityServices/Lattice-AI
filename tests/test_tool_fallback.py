import urllib.error

from lattice_ai.builtins import install_builtins
from lattice_ai.models import Tool
from lattice_ai.tools import ToolRegistry


def test_cli_falls_back_to_builtin_with_same_name():
    registry = ToolRegistry()
    registry.register_builtin("fb", "fb", {}, {}, lambda args: {"value": args.get("x", 0)})
    registry.register(Tool(name="fb", description="cli", runner="cli", command=["missing-xyz-binary-1", "{x}"]))
    result = registry.run("fb", {"x": 3})
    assert result["fallback"] is True
    assert result["value"] == 3


def test_cli_without_builtin_still_returns_not_found():
    registry = ToolRegistry()
    registry.register(Tool(name="fb2", description="cli", runner="cli", command=["missing-xyz-binary-2"]))
    result = registry.run("fb2", {})
    assert "not found" in result["error"]
    assert "fallback" not in result


def test_install_builtins_registers_vuln_fallback_builtins():
    registry = ToolRegistry()
    install_builtins(registry)
    for name in ("nuclei", "sqlmap", "dalfox"):
        assert name in registry._builtins
        # registry entries shadow the builtin Tool entry with runner="cli";
        # the sim function remains reachable via the missing-executable fallback.
        # all three are registry cli tools now (sqlmap migrated in task D);
        # the sim function remains reachable via the missing-executable fallback
        assert registry.get(name).runner == "cli"


def test_nuclei_cli_falls_back_to_light_builtin(monkeypatch):
    from lattice_ai import builtins

    def fake_fetch(url, timeout=8):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(builtins, "_fetch", fake_fetch)
    registry = ToolRegistry()
    install_builtins(registry)
    registry.register(Tool(name="nuclei", description="real", runner="cli", command=["nuclei", "-u", "{target}"]))
    result = registry.run("nuclei", {"target": "example.com"})
    assert result.get("fallback") is True
    assert "findings" in result
    assert result["count"] == 0
