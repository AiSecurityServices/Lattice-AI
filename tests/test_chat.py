import pytest

from lattice_ai.chat import ChatAgent
from lattice_ai.events import EventLog
from lattice_ai.models import Skill, Stage, Template, Tool, ToolBinding
from lattice_ai.tools import ToolError, ToolRegistry


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


def _make_template():
    return Template(
        id="t1",
        name="demo",
        start="a",
        stages=[
            Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out", defaults={"msg": "hello"})]),
        ],
        tools=[Tool(name="echo", description="echo", runner="builtin")],
    )


def _registry():
    reg = ToolRegistry()
    reg.register_builtin("echo", "echo", {}, {}, lambda args: {"value": args.get("msg", "")})
    return reg


def test_chat_answers_without_tools(tmp_path):
    provider = FakeProvider([{"content": "hi there", "tool_calls": []}])
    log = EventLog(tmp_path / "s.jsonl")
    agent = ChatAgent(provider, _make_template(), _registry(), log)
    result = agent.respond("hello")
    assert result["content"] == "hi there"
    assert result["facts"] == {}
    roles = [e.data["role"] for e in log.read() if e.type == "chat_message"]
    assert roles == ["user", "assistant"]


def test_chat_runs_workflow_tool(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "run_workflow", "arguments": {"target": "example.com"}}]},
        {"content": "done", "tool_calls": []},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    agent = ChatAgent(provider, _make_template(), _registry(), log)
    result = agent.respond("run the workflow")
    assert result["content"] == "done"
    assert result["facts"]["out"] == {"value": "hello"}
    types = [e.type for e in log.read()]
    assert "run_started" in types
    assert any(e.type == "tool_result" and e.data["tool"] == "run_workflow" for e in log.read())


def test_chat_runs_bound_tool(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"msg": "hi"}}]},
        {"content": "ok", "tool_calls": []},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    agent = ChatAgent(provider, _make_template(), _registry(), log)
    result = agent.respond("echo hi")
    assert result["facts"]["echo"] == {"value": "hi"}
    assert result["content"] == "ok"


def test_chat_rejects_unbound_tool(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "evil", "arguments": {}}]},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    agent = ChatAgent(provider, _make_template(), _registry(), log)
    with pytest.raises(ToolError):
        agent.respond("do evil")


def test_chat_redacts_secret(tmp_path):
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "login", "arguments": {}}]},
        {"content": "done", "tool_calls": []},
    ])
    reg = ToolRegistry()
    reg.register_builtin("login", "login", {}, {}, lambda args: {"password": "s3cret"})
    reg.get("login").secret_fields = ["password"]
    template = Template(
        id="t1",
        name="demo",
        start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="login", key="cred")])],
        tools=[Tool(name="login", description="login", runner="builtin", secret_fields=["password"])],
    )
    log = EventLog(tmp_path / "s.jsonl")
    agent = ChatAgent(provider, template, reg, log)
    agent.respond("login")
    log.flush()
    assert "s3cret" not in log.path.read_text(encoding="utf-8")


def test_chat_includes_template_skills(tmp_path):
    provider = FakeProvider([{"content": "ok", "tool_calls": []}])
    template = Template(
        id="t1",
        name="demo",
        start="a",
        stages=[Stage(id="a", name="a")],
        tools=[],
        skills=[Skill(name="recon", content="# Recon\n1. enumerate subdomains")],
    )
    log = EventLog(tmp_path / "s.jsonl")
    agent = ChatAgent(provider, template, _registry(), log)
    agent.respond("hello")
    system = provider.calls[0]["messages"][0]["content"]
    assert "recon" in system
    assert "enumerate subdomains" in system


def test_chat_carries_initial_facts(tmp_path):
    provider = FakeProvider([{"content": "ok", "tool_calls": []}])
    template = _make_template()
    log = EventLog(tmp_path / "s.jsonl")
    agent = ChatAgent(provider, template, _registry(), log)
    result = agent.respond("analyze", initial_facts={"ports": {"stdout": "80,443"}})
    assert result["facts"]["ports"] == {"stdout": "80,443"}
    system = provider.calls[0]["messages"][0]["content"]
    assert "80,443" in system
