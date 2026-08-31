import json
import os

import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.models import to_dict
from lattice_ai.recipes import load_bundled_recipes
from lattice_ai.workspace import ProjectStore


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    template_store.save(server._LITE_PENTEST_TEMPLATE["id"], server._LITE_PENTEST_TEMPLATE)
    for name, data in server._DEFAULT_SKILLS.items():
        skill_store.save(name, data)
    for recipe in load_bundled_recipes():
        tool_store.save(recipe.name, to_dict(recipe))
    store = ProjectStore(
        tmp_path / "projects",
        seed_settings={"provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": ""},
    )
    monkeypatch.setattr(rt, "_template_store", template_store)
    monkeypatch.setattr(rt, "_tool_store", tool_store)
    monkeypatch.setattr(rt, "_skill_store", skill_store)
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    yield


client = TestClient(server.app)


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, tools):
        return self.responses.pop(0)

    def stream_chat(self, messages, tools):
        r = self.responses.pop(0)
        content = r.get("content") or ""
        if content:
            yield {"type": "delta", "content": content}
        yield {"type": "done", "content": content, "tool_calls": r.get("tool_calls") or []}


def _template():
    return {
        "id": "t1",
        "name": "demo",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "record_finding", "key": "rf"}]}],
        "tools": [{"name": "record_finding", "description": "record", "runner": "builtin"}],
    }


def test_record_finding_tool_persists(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "record_finding", "arguments": {"title": "XSS 反射", "severity": "high", "target": "example.com"}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    r = client.post("/api/run", json={"template": _template(), "target": "example.com"})
    assert r.status_code == 200
    run_id = r.json()["id"]
    findings = client.get("/api/findings").json()["findings"]
    mine = [f for f in findings if f.get("run_id") == run_id]
    assert any(f["title"] == "XSS 反射" and f["severity"] == "high" for f in mine)


def test_persist_evidence_tools_handles_finding_loot_and_host():
    project = rt._active()
    project.save_run("r1", {"id": "r1", "template_id": "t", "target": "x", "kind": "run", "events": [], "facts": {}})
    events = [
        {"type": "tool_result", "data": {"tool": "record_finding", "result": {"recorded": True, "finding": {"title": "越权", "severity": "high"}}}},
        {"type": "tool_result", "data": {"tool": "record_loot", "result": {"recorded": True, "loot": {"token": "abc"}}}},
        {"type": "tool_result", "data": {"tool": "record_host", "result": {"recorded": True, "asset": {"kind": "host", "value": "api.example.com"}}}},
    ]
    server._persist_evidence_tools(project, "r1", "s1", events)

    assert any(f["title"] == "越权" and f["session_id"] == "s1" for f in project.findings.values())
    assert project.runs["r1"]["loot"] == [{"token": "abc"}]
    assert any(a["value"] == "api.example.com" and a["session_id"] == "s1" for a in project.assets.list_assets())


def test_stream_delta_cap_limits_forwarded_events():
    class StreamProvider:
        def stream_chat(self, messages, tools):
            for _ in range(50):
                yield {"type": "delta", "content": "x" * 200}
            yield {"type": "done", "content": "full", "tool_calls": []}

    sink = []
    wrapped = server._StreamingProvider(StreamProvider(), sink.append)
    result = wrapped.chat([], [])
    total = sum(len(e["content"]) for e in sink)
    assert total <= server._MAX_STREAM_DELTA_CHARS
    assert result["content"] == "full"


def test_stage_agent_instructs_evidence_tools(tmp_path):
    from lattice_ai.agent import StageAgent
    from lattice_ai.events import EventLog
    from lattice_ai.models import Stage, ToolBinding
    from lattice_ai.tools import ToolRegistry

    captured = {}

    class P:
        def chat(self, messages, tools):
            captured["system"] = messages[0]["content"]
            return {"content": "done", "tool_calls": []}

    reg = ToolRegistry()
    reg.register_builtin("record_finding", "rf", {}, {}, lambda args: {"recorded": True, "finding": {}})
    stage = Stage(id="s", name="发现", tools=[ToolBinding(tool="record_finding", key="rf")])
    StageAgent(P(), reg, EventLog(tmp_path / "s.jsonl")).run_stage(stage, "example.com", {})
    assert "record_finding" in captured["system"]
    assert "必须" in captured["system"]


def test_recorded_findings_from_events():
    events = [
        {"type": "tool_result", "data": {"tool": "record_finding", "result": {"recorded": True, "finding": {"title": "越权", "severity": "high"}}}},
        {"type": "tool_result", "data": {"tool": "echo", "result": {}}},
        {"type": "tool_result", "data": {"tool": "record_finding", "result": {"recorded": True, "finding": {}}}},
    ]
    out = server._recorded_findings_from_events(events)
    assert [f["title"] for f in out] == ["越权"]


def test_execute_run_grounds_report_in_recorded_findings(monkeypatch):
    from lattice_ai import agent as agent_mod
    from lattice_ai.models import Template, from_dict

    captured = {}

    class FakeStream(agent_mod.WorkflowAgent):
        def __init__(self, provider, registry, event_log, approver=None, max_iterations=25, prior_context=None):
            self.provider = provider
            self.event_log = event_log

        def run(self, template, target, *, cwd=None):
            self.event_log.append(
                "tool_result",
                {"tool": "record_finding", "result": {"recorded": True, "finding": {"title": "越权", "severity": "high"}}},
            )
            return {}

    monkeypatch.setattr(rt, "WorkflowAgent", FakeStream)

    def fake_report(provider, facts, template):
        captured["facts"] = facts
        return "# R"

    monkeypatch.setattr(rt, "generate_report", fake_report)
    tpl = from_dict(Template, {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []})
    rt._execute_run(tpl, object(), "example.com", True, self_check=False)
    assert captured["facts"]["recorded_findings"][0]["title"] == "越权"


def test_cli_uses_resolved_path_outside_path(tmp_path):
    import shutil
    import sys

    from lattice_ai.models import Tool
    from lattice_ai.tools import ToolRegistry, add_tool_path

    exe = "probe_py.exe" if os.name == "nt" else "probe_py"
    target = tmp_path / exe
    shutil.copy2(sys.executable, target)
    add_tool_path(str(tmp_path))
    registry = ToolRegistry()
    registry.register(Tool(name="probe_py", description="d", runner="cli", command=["probe_py", "-c", "print('HI')"]))
    result = registry.run("probe_py", {})
    assert "HI" in result["stdout"]
    assert "fallback" not in result


def test_cli_wraps_bat_through_cmd(tmp_path):
    if os.name != "nt":
        return

    from lattice_ai.models import Tool
    from lattice_ai.tools import ToolRegistry, add_tool_path

    bat = tmp_path / "probe_tool.bat"
    bat.write_text("@echo off\r\necho BAT_OK %1\r\n", encoding="ascii")
    add_tool_path(str(tmp_path))
    registry = ToolRegistry()
    registry.register(Tool(name="probe_tool", description="d", runner="cli", command=["probe_tool", "hello"]))
    result = registry.run("probe_tool", {})
    assert "BAT_OK" in result["stdout"]
    assert "fallback" not in result
