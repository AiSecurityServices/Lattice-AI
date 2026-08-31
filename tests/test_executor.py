from lattice_ai.agent import StageAgent
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.models import Stage, Template, ToolBinding
from lattice_ai.tools import ToolRegistry


class _ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, tools):
        return self.responses.pop(0)


def _registry_with_echo():
    reg = ToolRegistry()
    reg.register_builtin("echo", "echo", {}, {}, lambda args: {"value": args.get("target")})
    return reg


def test_linear_run(tmp_path):
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[
            Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="first")]),
            Stage(id="b", name="b", depends_on=["a"], tools=[ToolBinding(tool="echo", key="second")]),
        ],
    )
    log = EventLog(tmp_path / "s.jsonl")
    rs = Executor(template, _registry_with_echo(), log, run_id="r").run("example.com")
    facts = rs.facts
    assert facts["first"] == {"value": "example.com"}
    assert facts["second"] == {"value": "example.com"}
    assert [e.type for e in log.read()] == [
        "run_started",
        "stage_started",
        "tool_call",
        "tool_result",
        "stage_finished",
        "stage_started",
        "tool_call",
        "tool_result",
        "stage_finished",
        "run_finished",
    ]


def test_conditional_skip(tmp_path):
    reg = ToolRegistry()
    reg.register_builtin("mark", "mark", {}, {}, lambda args: {"ok": True})
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[
            Stage(id="a", name="a", tools=[ToolBinding(tool="mark", key="m")]),
            Stage(id="c", name="c", depends_on=["a"], condition={"op": "truthy", "key": "m.ok"}),
        ],
    )
    log = EventLog(tmp_path / "s.jsonl")
    Executor(template, reg, log).run("example.com")
    stage_starts = [e.data["stage"] for e in log.read() if e.type == "stage_started"]
    assert stage_starts == ["a", "c"]


def test_sequential_default(tmp_path):
    reg = ToolRegistry()
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a"), Stage(id="b", name="b"), Stage(id="c", name="c")],
    )
    log = EventLog(tmp_path / "s.jsonl")
    Executor(template, reg, log).run("example.com")
    stage_starts = [e.data["stage"] for e in log.read() if e.type == "stage_started"]
    assert stage_starts == ["a", "b", "c"]


def test_args_from_injects_facts(tmp_path):
    reg = ToolRegistry()
    reg.register_builtin("emit", "emit", {}, {}, lambda args: {"url": args.get("url")})
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[
            Stage(id="a", name="a", tools=[ToolBinding(tool="emit", key="first", defaults={"url": "https://one"})]),
            Stage(id="b", name="b", depends_on=["a"], tools=[ToolBinding(tool="emit", key="second", args_from={"url": "first.url"})]),
        ],
    )
    log = EventLog(tmp_path / "s.jsonl")
    facts = Executor(template, reg, log, run_id="r").run("example.com").facts
    assert facts["first"] == {"url": "https://one"}
    assert facts["second"] == {"url": "https://one"}


def test_secret_fields_redacted_in_log(tmp_path):
    reg = ToolRegistry()
    reg.register_builtin("login", "login", {}, {}, lambda args: {"user": "alice", "password": "s3cret"})
    reg.get("login").secret_fields = ["password"]
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="login", key="cred")])],
    )
    log = EventLog(tmp_path / "s.jsonl")
    facts = Executor(template, reg, log, run_id="r").run("example.com").facts
    assert facts["cred"]["password"] == "s3cret"
    logged = [e for e in log.read() if e.type == "tool_result"][0]
    assert logged.data["result"]["password"] == "[REDACTED]"


def test_executor_autonomous_mode(tmp_path):
    provider = _ScriptedProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"msg": "hi"}}]},
        {"content": "done", "tool_calls": []},
    ])
    reg = ToolRegistry()
    reg.register_builtin("echo", "echo", {}, {}, lambda args: {"value": args.get("msg")})
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out")])],
    )
    log = EventLog(tmp_path / "s.jsonl")
    agent = StageAgent(provider, reg, log)
    facts = Executor(template, reg, log, run_id="r").run("example.com", agent=agent).facts
    assert facts["out"] == {"value": "hi"}


def test_secret_does_not_leak_across_stages(tmp_path):
    reg = ToolRegistry()
    reg.register_builtin("cred", "cred", {}, {}, lambda args: {"password": "s3cret", "user": "alice"})
    reg.get("cred").secret_fields = ["password"]
    reg.register_builtin("use", "use", {}, {}, lambda args: {"ok": True})
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[
            Stage(id="a", name="a", tools=[ToolBinding(tool="cred", key="c")]),
            Stage(id="b", name="b", depends_on=["a"], tools=[ToolBinding(tool="use", key="u", args_from={"password": "c.password"})]),
        ],
    )
    log = EventLog(tmp_path / "s.jsonl")
    facts = Executor(template, reg, log, run_id="r").run("example.com").facts
    assert facts["c"]["password"] == "s3cret"
    log.flush()
    assert "s3cret" not in log.path.read_text(encoding="utf-8")
    use_call = [e for e in log.read() if e.type == "tool_call" and e.data["tool"] == "use"][0]
    assert use_call.data["args"]["password"] == "[REDACTED]"
    run_finished = [e for e in log.read() if e.type == "run_finished"][0]
    assert run_finished.data["facts"]["c"]["password"] == "[REDACTED]"


def test_missing_tool_does_not_abort_run(tmp_path):
    from lattice_ai.models import Stage, Template, ToolBinding
    from lattice_ai.tools import Tool, ToolRegistry
    from lattice_ai.executor import Executor

    reg = ToolRegistry()
    reg.register(Tool(name="nope", description="d", runner="cli", command=["definitely-not-a-real-command-xyz"]))
    template = Template(
        id="t", name="n", start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="nope", key="out")])],
    )
    facts = Executor(template, reg, EventLog(tmp_path / "s.jsonl"), run_id="r").run("example.com").facts
    assert "not found" in facts["out"]["error"]
