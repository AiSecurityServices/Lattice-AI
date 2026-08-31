import sys

import pytest

from lattice_ai.builtins import install_builtins
from lattice_ai.models import Tool
from lattice_ai.tools import ApprovalDenied, DangerDenied, ScopeViolation, ToolError, ToolRegistry, classify_target, redact


def test_builtin_tool():
    reg = ToolRegistry()
    reg.register_builtin("echo", "echo", {}, {}, lambda args: {"value": args["msg"]})
    assert reg.run("echo", {"msg": "hi"}) == {"value": "hi"}


def test_cli_tool_returns_stdout():
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="print",
            description="print",
            runner="cli",
            command=[sys.executable, "-c", "import sys; print(sys.argv[1])", "{msg}"],
        )
    )
    result = reg.run("print", {"msg": "hello"})
    assert result["stdout"].strip() == "hello"
    assert result["returncode"] == 0


def test_validation_rejects_missing_required():
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="t",
            description="d",
            runner="cli",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            command=["nmap", "{x}"],
        )
    )
    with pytest.raises(ToolError):
        reg.run("t", {})


def test_unknown_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(ToolError):
        reg.run("nope", {})


def test_builtin_resolves_by_name_from_catalog():
    reg = ToolRegistry()
    install_builtins(reg)
    reg.register(Tool(name="echo", description="override", runner="builtin"))
    assert reg.run("echo", {"msg": "ok"}) == {"value": "ok"}


def test_output_validation_rejects_invalid():
    reg = ToolRegistry()
    reg.register_builtin(
        "t",
        "d",
        {},
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        lambda args: {"other": 1},
    )
    with pytest.raises(ToolError):
        reg.run("t", {})


def test_approval_deny_blocks():
    reg = ToolRegistry()
    reg.register_builtin("t", "d", {}, {}, lambda args: {"ok": True})
    reg.get("t").approval = "deny"
    with pytest.raises(ApprovalDenied):
        reg.run("t", {})


def test_approval_ask_requires_approver():
    reg = ToolRegistry()
    reg.register_builtin("t", "d", {}, {}, lambda args: {"ok": True})
    reg.get("t").approval = "ask"
    with pytest.raises(ApprovalDenied):
        reg.run("t", {})


def test_approval_ask_approver_allows():
    reg = ToolRegistry()
    reg.register_builtin("t", "d", {}, {}, lambda args: {"ok": True})
    reg.get("t").approval = "ask"
    result = reg.run("t", {}, approver=lambda tool, args: True)
    assert result == {"ok": True}


def test_approval_ask_approver_rejects():
    reg = ToolRegistry()
    reg.register_builtin("t", "d", {}, {}, lambda args: {"ok": True})
    reg.get("t").approval = "ask"
    with pytest.raises(ApprovalDenied):
        reg.run("t", {}, approver=lambda tool, args: False)


def test_redact_secret_fields():
    result = {"user": "alice", "password": "s3cret", "nested": {"token": "abc", "keep": 1}}
    redacted = redact(result, ["password", "nested.token"])
    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["keep"] == 1
    assert result["password"] == "s3cret"


def test_missing_placeholder_raises_toolerror():
    reg = ToolRegistry()
    reg.register(Tool(name="t", description="d", runner="cli", command=["echo", "{missing}"]))
    with pytest.raises(ToolError):
        reg.run("t", {})


def test_missing_executable_returns_error_result():
    reg = ToolRegistry()
    reg.register(Tool(name="t", description="d", runner="cli", command=["definitely-not-a-real-command-xyz"]))
    result = reg.run("t", {})
    assert "not found" in result["error"]


def test_secret_field_typo_rejected_at_register():
    reg = ToolRegistry()
    tool = Tool(
        name="t",
        description="d",
        runner="cli",
        command=["echo"],
        output={"type": "object", "properties": {"password": {"type": "string"}}},
        secret_fields=["pasword"],
    )
    with pytest.raises(ToolError):
        reg.register(tool)


def test_register_and_dispatch_adapter():
    from lattice_ai.models import Tool
    from lattice_ai.tools import Adapter, ToolRegistry, register_adapter

    class FakeAdapter(Adapter):
        def __init__(self):
            super().__init__("fake")

        def invoke(self, tool, args, *, timeout=60.0, cwd=None):
            return {"echo": args}

    register_adapter(FakeAdapter())
    registry = ToolRegistry()
    registry.register(Tool(name="f", runner="adapter", adapter="fake"))
    assert registry.run("f", {"a": 1})["echo"] == {"a": 1}


def test_run_unknown_adapter_raises():
    from lattice_ai.models import Tool
    from lattice_ai.tools import ToolError, ToolRegistry

    registry = ToolRegistry()
    try:
        registry.register(Tool(name="m", runner="adapter", adapter="missing"))
        raise AssertionError("should have raised")
    except ToolError as exc:
        assert "missing" in str(exc)


def test_register_adapter_tool_requires_handler():
    from lattice_ai.models import Tool
    from lattice_ai.tools import ToolError, ToolRegistry

    registry = ToolRegistry()
    try:
        registry.register(Tool(name="n", runner="adapter", adapter="nope"))
        raise AssertionError("should have raised")
    except ToolError as exc:
        assert "nope" in str(exc)


def test_tool_available_builtin_is_always_true():
    from lattice_ai.models import Tool
    from lattice_ai.tools import tool_available, tool_status

    t = Tool(name="echo", runner="builtin")
    assert tool_available(t) is True
    assert tool_status(t) == "builtin"


def test_tool_available_cli_missing_is_false():
    from lattice_ai.models import Tool
    from lattice_ai.tools import tool_available, tool_status

    t = Tool(name="definitely_missing_xyz", runner="cli", command=["definitely_missing_xyz", "-u", "{target}"])
    assert tool_available(t) is False
    assert tool_status(t) == "unavailable"


def test_classify_target_types():
    assert classify_target("https://example.com") == "web"
    assert classify_target("example.com:8080") == "service"
    assert classify_target("192.0.2.1") == "network"
    assert classify_target("example.com") == "host"


def test_scope_blocks_wrong_target_type():
    tool = Tool(name="x", runner="cli", command=["echo", "{target}"], scope=["web"])
    registry = ToolRegistry()
    registry.register(tool)
    try:
        registry.run("x", {"target": "192.0.2.1"})
        assert False, "expected ToolError"
    except ToolError:
        pass


def test_tool_status_unregistered_adapter_is_unavailable():
    from lattice_ai.models import Tool
    from lattice_ai.tools import tool_available, tool_status

    t = Tool(name="x", runner="adapter", adapter="nope")
    assert tool_available(t) is False
    assert tool_status(t) == "unavailable"


def test_add_tool_path_makes_executable_visible():
    import os
    import tempfile

    from lattice_ai.tools import add_tool_path, find_executable

    with tempfile.TemporaryDirectory() as d:
        exe = "probe_bin" + (".exe" if os.name == "nt" else "")
        p = os.path.join(d, exe)
        open(p, "w").write("")
        if os.name != "nt":
            os.chmod(p, 0o755)
        assert find_executable("probe_bin") is None
        add_tool_path(d)
        assert find_executable("probe_bin") is not None


def test_scope_policy_blocks_unlisted_domain():
    registry = ToolRegistry()
    registry.register(Tool(name="cli", runner="cli", command=["echo", "{target}"]))
    try:
        registry.run("cli", {"target": "https://evil.com"}, scope_policy={"allow_domains": ["good.com"]})
    except ScopeViolation:
        pass
    else:
        raise AssertionError("expected ScopeViolation")


def test_danger_policy_blocks_destructive_tool():
    registry = ToolRegistry()
    registry.register(Tool(name="shell", runner="cli", command=["rm", "-rf", "{target}"]))
    try:
        registry.run("shell", {"target": "/tmp/x"}, danger_policy={"level": "strict", "whitelist": []})
    except DangerDenied:
        pass
    else:
        raise AssertionError("expected DangerDenied")


def test_security_context_applies_to_all_tools():
    registry = ToolRegistry()
    registry.set_security_context(scope_policy={"allow_domains": ["good.com"]})
    registry.register(Tool(name="cli", runner="cli", command=["echo", "{target}"]))
    try:
        registry.run("cli", {"target": "https://evil.com"})
    except ScopeViolation:
        pass
    else:
        raise AssertionError("expected ScopeViolation")
