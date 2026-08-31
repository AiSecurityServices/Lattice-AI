import pytest

from lattice_ai.agent import StageAgent, WorkflowAgent, tool_to_function_spec
from lattice_ai.events import EventLog
from lattice_ai.models import SkillBinding, Stage, Template, Tool, ToolBinding
from lattice_ai.tools import ApprovalDenied, ToolError, ToolRegistry


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


def _echo_registry():
    reg = ToolRegistry()
    reg.register_builtin("echo", "echo", {}, {}, lambda args: {"value": args.get("msg")})
    return reg


def test_agent_loop(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"msg": "hi"}}]},
        {"content": "done", "tool_calls": []},
    ])
    reg = _echo_registry()
    log = EventLog(tmp_path / "s.jsonl")
    stage = Stage(id="a", name="a", goal="do it", tools=[ToolBinding(tool="echo", key="out")])
    agent = StageAgent(provider, reg, log)
    facts = agent.run_stage(stage, "example.com", {})
    assert facts["out"] == {"value": "hi"}
    assert [e.type for e in log.read()] == ["agent_message", "tool_call", "tool_result", "agent_message"]


def test_agent_rejects_unbound_tool(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "evil", "arguments": {}}]},
    ])
    reg = _echo_registry()
    log = EventLog(tmp_path / "s.jsonl")
    stage = Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out")])
    agent = StageAgent(provider, reg, log)
    with pytest.raises(ToolError):
        agent.run_stage(stage, "example.com", {})


def test_agent_approval_rejects(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
    ])
    reg = _echo_registry()
    reg.get("echo").approval = "ask"
    log = EventLog(tmp_path / "s.jsonl")
    stage = Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out")])
    agent = StageAgent(provider, reg, log, approver=lambda tool, args: False)
    with pytest.raises(ApprovalDenied):
        agent.run_stage(stage, "example.com", {})


def test_tool_to_function_spec():
    tool = Tool(name="echo", description="d", parameters={"type": "object", "properties": {"msg": {"type": "string"}}})
    spec = tool_to_function_spec(tool)
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "echo"
    assert spec["function"]["parameters"]["properties"]["msg"]["type"] == "string"


def test_agent_updates_secret_paths(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "login", "arguments": {}}]},
        {"content": "done", "tool_calls": []},
    ])
    reg = ToolRegistry()
    reg.register_builtin("login", "login", {}, {}, lambda args: {"password": "s3cret"})
    reg.get("login").secret_fields = ["password"]
    log = EventLog(tmp_path / "s.jsonl")
    stage = Stage(id="a", name="a", tools=[ToolBinding(tool="login", key="cred")])
    agent = StageAgent(provider, reg, log)
    secret_paths = set()
    facts = agent.run_stage(stage, "example.com", {}, secret_paths=secret_paths)
    assert facts["cred"]["password"] == "s3cret"
    assert "cred.password" in secret_paths


def test_agent_redacts_secret_in_log(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "creds", "arguments": {}}]},
        {"content": None, "tool_calls": [{"id": "c2", "name": "use", "arguments": {"password": "s3cret"}}]},
        {"content": "done", "tool_calls": []},
    ])
    reg = ToolRegistry()
    reg.register_builtin("creds", "creds", {}, {}, lambda args: {"password": "s3cret"})
    reg.get("creds").secret_fields = ["password"]
    reg.register_builtin("use", "use", {}, {}, lambda args: {"ok": True})
    log = EventLog(tmp_path / "s.jsonl")
    stage = Stage(id="a", name="a", tools=[ToolBinding(tool="creds", key="c"), ToolBinding(tool="use", key="u")])
    agent = StageAgent(provider, reg, log)
    secret_paths = set()
    agent.run_stage(stage, "example.com", {}, secret_paths=secret_paths)
    log.flush()
    assert "s3cret" not in log.path.read_text(encoding="utf-8")


def test_agent_injects_bound_skill(tmp_path):
    provider = FakeProvider([{"content": "done", "tool_calls": []}])
    reg = _echo_registry()
    log = EventLog(tmp_path / "s.jsonl")
    stage = Stage(id="a", name="a", skills=[SkillBinding(skill="recon-basics")])
    agent = StageAgent(provider, reg, log, skills={"recon-basics": "# Recon\n1. enumerate subdomains"})
    agent.run_stage(stage, "example.com", {})
    system = provider.calls[0]["messages"][0]["content"]
    assert "recon-basics" in system
    assert "enumerate subdomains" in system


def test_agent_skips_disabled_or_missing_skill(tmp_path):
    provider = FakeProvider([{"content": "done", "tool_calls": []}])
    reg = _echo_registry()
    log = EventLog(tmp_path / "s.jsonl")
    stage = Stage(
        id="a",
        name="a",
        skills=[SkillBinding(skill="present"), SkillBinding(skill="missing"), SkillBinding(skill="off", enabled=False)],
    )
    agent = StageAgent(provider, reg, log, skills={"present": "present content", "off": "off content"})
    agent.run_stage(stage, "example.com", {})
    system = provider.calls[0]["messages"][0]["content"]
    assert "present content" in system
    assert "off content" not in system


def test_workflow_agent_runs_tools(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"msg": "hi"}}]},
        {"content": "done", "tool_calls": []},
    ])
    reg = _echo_registry()
    log = EventLog(tmp_path / "s.jsonl")
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a")],
        tools=[Tool(name="echo", description="echo", runner="builtin")],
    )
    agent = WorkflowAgent(provider, reg, log)
    facts = agent.run(template, "example.com")
    assert facts["echo"] == {"value": "hi"}
