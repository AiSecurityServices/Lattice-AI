"""T-T3 tier tests: tool_tier events on the real/sim paths, binding.tier
enforcement, and run-record tier counts. All offline via fake executables."""
import json

import pytest

from lattice_ai import toolchain_registry as tcr
from lattice_ai.builtins import install_builtins
from lattice_ai.events import EventLog
from lattice_ai.models import RunState, Stage, Template, ToolBinding, Tool
from lattice_ai.tools import ToolError, ToolRegistry, add_tool_path

from helpers_fakeexe import make_fake_exe, version_flag_of
import os
import shutil


@pytest.fixture(autouse=True)
def _isolated_tool_paths():
    """add_tool_path and the identity/version caches are module-global; tests
    must not see each other's fake executables."""
    from lattice_ai import tools as tools_mod

    saved_paths = list(tools_mod._EXTRA_TOOL_PATHS)
    saved_identity = dict(tools_mod._identity_cache)
    saved_versions = dict(tcr._version_cache)
    tools_mod._EXTRA_TOOL_PATHS.clear()
    tools_mod._identity_cache.clear()
    tcr._version_cache.clear()
    yield
    tools_mod._EXTRA_TOOL_PATHS[:] = saved_paths
    tools_mod._identity_cache.clear()
    tools_mod._identity_cache.update(saved_identity)
    tcr._version_cache.clear()
    tcr._version_cache.update(saved_versions)


def _fake_tool(tmp_path, name, *, payload, broken_identity=False, payload_stderr=""):
    entry = tcr.get_entry(name)
    assert entry, f"{name} not in registry"
    if broken_identity:
        # a same-name binary that is NOT the real tool: identity probe answers
        # with an unrelated string
        make_fake_exe(tmp_path, name, version_flag=version_flag_of(entry.version_cmd),
                      version_line="just some other program", payload=payload)
    else:
        make_fake_exe(tmp_path, name, version_flag=version_flag_of(entry.version_cmd),
                      version_line=f"v2.6.7-test", payload=payload)
    add_tool_path(str(tmp_path))


def _registry():
    registry = ToolRegistry()
    install_builtins(registry)
    return registry


def test_real_tool_run_emits_tool_tier_real(tmp_path):
    _fake_tool(tmp_path, "subfinder", payload=json.dumps({"host": "x.example.com"}))
    log = EventLog(tmp_path / "ev.jsonl")
    registry = _registry()
    result = registry.run("subfinder", {"target": "example.com"}, event_log=log)
    assert result["_tool_tier"] == {"tier": "real", "reason": "installed"}
    tiers = [e.data for e in log.read() if e.type == "tool_tier"]
    assert {"tool": "subfinder", "tier": "real", "reason": "installed"} in tiers


def test_missing_tool_falls_back_and_emits_tool_tier_sim(tmp_path):
    # nothing named subfinder on PATH (tmp_path empty)
    log = EventLog(tmp_path / "ev.jsonl")
    registry = _registry()
    result = registry.run("subfinder", {"target": "example.com"}, event_log=log)
    assert result["fallback"] is True
    assert result["_tool_tier"] == {"tier": "sim", "reason": "missing_fallback"}
    tiers = [e.data for e in log.read() if e.type == "tool_tier"]
    assert tiers[-1]["tier"] == "sim" and tiers[-1]["reason"] == "missing_fallback"


def test_identity_collapsed_binary_falls_back_to_sim(tmp_path):
    # a binary that shares the name but is not the real tool -> sim
    # (payload must not contain a "v" that could satisfy the version regex)
    _fake_tool(tmp_path, "subfinder", payload=json.dumps({"host": "collision"}), broken_identity=True)
    registry = _registry()
    result = registry.run("subfinder", {"target": "example.com"}, event_log=None)
    assert result["fallback"] is True


def test_tool_disappearing_midrun_falls_back(tmp_path):
    """Startup finds the exe; by execution time it is gone -> sim fallback."""
    entry = tcr.get_entry("subfinder")
    make_fake_exe(tmp_path, "subfinder", version_flag=version_flag_of(entry.version_cmd),
                  version_line="v2.6.7-test", payload=json.dumps({"host": "x"}))
    add_tool_path(str(tmp_path))
    registry = _registry()

    exe = tmp_path / ("subfinder.bat" if os.name == "nt" else "subfinder")
    real_run = registry.run

    def vanishing_run(name, args, **kwargs):
        if name == "subfinder" and exe.exists():
            exe.unlink()  # uninstall between identity check and execution
            shutil.rmtree(tmp_path, ignore_errors=True)
        return real_run(name, args, **kwargs)

    monkey_registry_run = vanishing_run
    # run through the registry directly; identity cache may hold the first hit,
    # so clear it to simulate a long gap
    tcr._version_cache.clear()
    from lattice_ai import tools as tools_mod
    tools_mod._identity_cache.clear()
    result = monkey_registry_run("subfinder", {"target": "example.com"}, event_log=None)
    assert result.get("fallback") is True or result["_tool_tier"]["tier"] == "sim"


def test_binding_tier_real_fails_loudly_when_missing(tmp_path):
    registry = _registry()
    template = Template(
        id="t", name="t", start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="subfinder", tier="real")])],
        tools=[],
    )
    from lattice_ai.executor import Executor
    log = EventLog(tmp_path / "ev.jsonl")
    executor = Executor(template, registry, log)
    rs = RunState(run_id="r1", template_id="t", target="example.com",
                  stage_status={"a": "pending"})
    import pytest
    with pytest.raises(ToolError):
        executor.run("example.com", approver=None, run_state=rs)


def test_binding_tier_real_passes_when_installed(tmp_path):
    _fake_tool(tmp_path, "subfinder", payload=json.dumps({"host": "x.example.com"}))
    registry = _registry()
    template = Template(
        id="t", name="t", start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="subfinder", tier="real", key="subs")])],
        tools=[],
    )
    from lattice_ai.executor import Executor
    log = EventLog(tmp_path / "ev.jsonl")
    executor = Executor(template, registry, log)
    rs = RunState(run_id="r1", template_id="t", target="example.com",
                  stage_status={"a": "pending"})
    executor.run("example.com", approver=None, run_state=rs)
    assert rs.tool_tiers["real"] == 1 and rs.tool_tiers["sim"] == 0
    assert rs.facts["subs"]["items"][0]["value"] == "x.example.com"


def test_binding_tier_sim_forces_simulator(tmp_path):
    # real tool IS installed, but the binding forces the simulator
    _fake_tool(tmp_path, "subfinder", payload=json.dumps({"host": "real.example.com"}))
    registry = _registry()
    template = Template(
        id="t", name="t", start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="subfinder", tier="sim", key="subs")])],
        tools=[],
    )
    from lattice_ai.executor import Executor
    log = EventLog(tmp_path / "ev.jsonl")
    executor = Executor(template, registry, log)
    rs = RunState(run_id="r1", template_id="t", target="example.com",
                  stage_status={"a": "pending"})
    executor.run("example.com", approver=None, run_state=rs)
    assert rs.tool_tiers["sim"] == 1 and rs.tool_tiers["real"] == 0


def test_run_state_counts_via_controlled_path(tmp_path):
    registry = _registry()
    template = Template(
        id="t", name="t", start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="subfinder", key="subs")])],
        tools=[],
    )
    from lattice_ai.executor import Executor
    log = EventLog(tmp_path / "ev.jsonl")
    executor = Executor(template, registry, log)
    rs = RunState(run_id="r1", template_id="t", target="example.com",
                  stage_status={"a": "pending"})
    executor.run("example.com", approver=None, run_state=rs)
    assert rs.tool_tiers["sim"] == 1 and rs.tool_tiers["real"] == 0


def test_tool_tiers_from_events_helper():
    """Run records derive tier counts from tool_tier events (also for stopped runs)."""
    from lattice_ai import runtime

    events = [
        {"type": "tool_tier", "data": {"tool": "subfinder", "tier": "real", "reason": "installed"}},
        {"type": "tool_tier", "data": {"tool": "httpx", "tier": "sim", "reason": "missing_fallback"}},
        {"type": "stage_started", "data": {}},
    ]
    assert runtime._tool_tiers_from_events(events) == {"real": 1, "sim": 1}
    assert runtime._tool_tiers_from_events([]) == {"real": 0, "sim": 0}
    assert runtime._tool_tiers_from_events(None) == {"real": 0, "sim": 0}
