import pytest

from lattice_ai.builtins import install_builtins
from lattice_ai.tools import ToolError, ToolRegistry, register_tool


@register_tool("demo_recon", description="demo recon", category="recon")
def _demo_recon(args):
    return {"ok": True}


def test_register_tool_decorator_adds_categorized_builtin():
    reg = ToolRegistry()
    install_builtins(reg)
    assert any(t.name == "demo_recon" for t in reg.list_tools("recon"))
    assert reg.get("demo_recon").category == "recon"


def test_list_tools_filters_by_category():
    reg = ToolRegistry()
    reg.register_builtin("plain", "plain", {}, {}, lambda args: {})
    install_builtins(reg)
    assert reg.list_tools() != []
    recon_names = {t.name for t in reg.list_tools("recon")}
    assert "demo_recon" in recon_names
    assert "plain" not in recon_names


def test_disable_tool_blocks_run_and_enable_restores():
    reg = ToolRegistry()
    reg.register_builtin("toggle", "toggle", {}, {}, lambda args: {"ok": True})
    assert reg.run("toggle", {})["ok"] is True
    reg.disable_tool("toggle")
    with pytest.raises(ToolError):
        reg.run("toggle", {})
    reg.enable_tool("toggle")
    assert reg.run("toggle", {})["ok"] is True


def test_run_respects_tool_enabled_flag():
    reg = ToolRegistry()
    reg.register_builtin("flag", "flag", {}, {}, lambda args: {"ok": True})
    reg.get("flag").enabled = False
    with pytest.raises(ToolError):
        reg.run("flag", {})
