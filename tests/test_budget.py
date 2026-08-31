import pytest

from lattice_ai.agent import StageAgent, WorkflowAgent
from lattice_ai.budget import Budget, BudgetExceeded, BudgetTracker
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.llm import OpenAICompatibleProvider, parse_response
from lattice_ai.models import Stage, Template, Tool, ToolBinding
from lattice_ai.run_state import load_run_state
from lattice_ai.tools import ToolRegistry


class _MemoryLog:
    def __init__(self):
        self.events = []

    def append(self, type_, data):
        self.events.append({"type": type_, "data": data})

    def read(self):
        return list(self.events)


class _ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, tools):
        return self.responses.pop(0) if self.responses else {"content": "done", "tool_calls": []}


def _usage_tool_provider(usage):
    """Provider that reports the given usage and always proposes one echo call,
    so the agent loop keeps iterating until a budget trips."""

    class P:
        def chat(self, messages, tools):
            return {
                "content": "working",
                "tool_calls": [{"id": f"c{len(messages)}", "name": "echo", "arguments": {}}],
                "usage": usage,
            }

    return P()


def _registry_with_echo():
    reg = ToolRegistry()
    reg.register_builtin("echo", "echo", {}, {}, lambda args: {"value": args.get("target")})
    return reg


def _two_stage_template():
    return Template(
        id="t",
        name="n",
        start="a",
        stages=[
            Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="first")]),
            Stage(id="b", name="b", depends_on=["a"], tools=[ToolBinding(tool="echo", key="second")]),
        ],
    )


# ---------- usage passthrough ----------

def test_parse_response_passes_usage_through():
    data = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    result = parse_response(data)
    assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def test_parse_response_usage_none_when_absent():
    result = parse_response({"choices": [{"message": {"content": "ok"}}]})
    assert result["usage"] is None


def test_provider_chat_surfaces_gateway_usage(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}'

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", lambda req, timeout=None: Resp())
    provider = OpenAICompatibleProvider("https://example.com/v1", "sk", "m")
    assert provider.chat([{"role": "user", "content": "hi"}], [])["usage"]["total_tokens"] == 10


# ---------- tracker dimensions ----------

def test_token_dimension_trips_on_check():
    tracker = BudgetTracker(Budget(max_tokens=100))
    tracker.add_usage({"total_tokens": 60})
    tracker.check()
    tracker.add_usage({"prompt_tokens": 30, "completion_tokens": 20})
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.check()
    assert exc_info.value.dimension == "tokens"
    assert exc_info.value.used == 110


def test_add_usage_is_none_safe():
    tracker = BudgetTracker(Budget(max_tokens=10))
    tracker.add_usage(None)
    tracker.add_usage({})
    tracker.check()


def test_tool_call_dimension_hard_cap():
    tracker = BudgetTracker(Budget(max_tool_calls=2))
    tracker.add_tool_call()
    tracker.add_tool_call()
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.add_tool_call()
    assert exc_info.value.dimension == "tool_calls"


def test_wall_dimension_with_injected_clock():
    now = [0.0]
    tracker = BudgetTracker(Budget(max_wall_seconds=10), clock=lambda: now[0])
    tracker.check()
    now[0] = 10.5
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.check()
    assert exc_info.value.dimension == "wall_seconds"


def test_cost_dimension_with_explicit_cost():
    tracker = BudgetTracker(Budget(max_cost_usd=1.0))
    tracker.add_usage({"total_tokens": 10}, cost=0.5)
    tracker.check()
    tracker.add_usage({"total_tokens": 10}, cost=0.75)
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.check()
    assert exc_info.value.dimension == "cost_usd"


def test_cost_computed_from_prices():
    tracker = BudgetTracker(Budget(), price_per_1k_input=0.5, price_per_1k_output=1.5)
    tracker.add_usage({"prompt_tokens": 1000, "completion_tokens": 1000})
    assert tracker.cost_usd == pytest.approx(2.0)


def test_default_tracker_has_generous_limits():
    tracker = BudgetTracker()
    assert tracker.budget.max_tokens == 2_000_000
    assert tracker.budget.max_tool_calls == 500
    assert tracker.budget.max_wall_seconds == 3600.0


# ---------- agent loop / executor integration ----------

def test_stage_agent_loop_trips_token_budget():
    log = _MemoryLog()
    agent = StageAgent(_usage_tool_provider({"total_tokens": 100}), _registry_with_echo(), log,
                       budget=BudgetTracker(Budget(max_tokens=150)))
    stage = Stage(id="a", name="a", tools=[ToolBinding(tool="echo")])
    with pytest.raises(BudgetExceeded) as exc_info:
        agent.run_stage(stage, "example.com", {})
    assert exc_info.value.dimension == "tokens"
    assert agent.budget.tokens_used == 200


def test_workflow_agent_winds_down_gracefully_on_budget_exceeded():
    log = _MemoryLog()
    template = Template(id="t", name="n", start="a", stages=[], tools=[Tool(name="echo", runner="builtin")])
    agent = WorkflowAgent(_usage_tool_provider({"total_tokens": 100}), _registry_with_echo(), log,
                          budget=BudgetTracker(Budget(max_tokens=150)))
    facts = agent.run(template, "example.com")
    assert "echo" in facts  # completed rounds keep their results; the run is not an error
    assert log.events[-1]["type"] == "budget_exceeded"
    assert log.events[-1]["data"] == {"dimension": "tokens", "used": 200, "limit": 150}


def test_executor_shares_tracker_with_agent_and_finishes_normally(tmp_path):
    log = EventLog(tmp_path / "run.jsonl")
    checkpoint = tmp_path / "state.json"
    agent = StageAgent(_usage_tool_provider({"total_tokens": 100}), _registry_with_echo(), log)
    executor = Executor(
        _two_stage_template(), _registry_with_echo(), log,
        run_id="r1", checkpoint_path=checkpoint,
        budget=BudgetTracker(Budget(max_tokens=150)),
    )
    rs = executor.run("example.com", agent=agent)

    assert agent.budget is executor.budget
    assert rs.stage_status == {"a": "skipped", "b": "skipped"}
    assert getattr(rs, "budget_status", "") == "exceeded"
    events = log.read()
    event_types = [e.type for e in events]
    assert "budget_exceeded" in event_types
    assert event_types[-1] == "run_finished"
    assert event_types.count("stage_finished") == 2  # stage 'a' breached mid-run, 'b' never ran: both skipped
    assert all(e.data.get("reason") == "budget_exceeded" for e in events if e.type == "stage_finished")

    persisted = load_run_state(checkpoint)
    assert persisted.budget_status == "exceeded"


def test_executor_controlled_path_counts_tool_calls(tmp_path):
    log = EventLog(tmp_path / "run.jsonl")
    executor = Executor(
        _two_stage_template(), _registry_with_echo(), log,
        run_id="r2", budget=BudgetTracker(Budget(max_tool_calls=0)),
    )
    rs = executor.run("example.com")
    assert rs.stage_status["a"] == "skipped"
    assert getattr(rs, "budget_status", "") == "exceeded"
    assert [e.type for e in log.read()].count("budget_exceeded") == 1


def test_executor_without_budget_uses_defaults_and_runs_normally(tmp_path):
    log = EventLog(tmp_path / "run.jsonl")
    rs = Executor(_two_stage_template(), _registry_with_echo(), log, run_id="r3").run("example.com")
    assert rs.stage_status == {"a": "completed", "b": "completed"}
    assert getattr(rs, "budget_status", "") == ""
    assert "budget_exceeded" not in [e.type for e in log.read()]


def test_budget_exceeded_checkpoint_is_resumable(tmp_path):
    log = EventLog(tmp_path / "run.jsonl")
    checkpoint = tmp_path / "state.json"
    agent = StageAgent(_usage_tool_provider({"total_tokens": 100}), _registry_with_echo(), log)
    executor = Executor(
        _two_stage_template(), _registry_with_echo(), log,
        run_id="r4", checkpoint_path=checkpoint, budget=BudgetTracker(Budget(max_tokens=150)),
    )
    executor.run("example.com", agent=agent)

    rs = load_run_state(checkpoint)
    assert rs.budget_status == "exceeded"

    # A fresh run with a fresh budget can pick the run back up from the checkpoint.
    rs.stage_status = {sid: "pending" for sid in rs.stage_status}
    rs.budget_status = ""
    log2 = EventLog(tmp_path / "run2.jsonl")
    agent2 = StageAgent(
        _ScriptedProvider([{"content": "done", "tool_calls": [], "usage": None}]),
        _registry_with_echo(), log2,
    )
    executor2 = Executor(
        _two_stage_template(), _registry_with_echo(), log2,
        run_id="r4", checkpoint_path=tmp_path / "state2.json",
        budget=BudgetTracker(Budget(max_tokens=1_000_000)),
    )
    rs2 = executor2.run("example.com", agent=agent2, run_state=rs)
    assert rs2.stage_status == {"a": "completed", "b": "completed"}
