from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.models import GateRule, RunState, Stage, Template, ToolBinding
from lattice_ai.run_state import (
    COMPLETED,
    FAILED,
    PENDING,
    READY,
    SKIPPED,
    load_run_state,
    next_ready,
    save_run_state,
    transitive_dependents,
)
from lattice_ai.tools import ToolRegistry


def _registry():
    reg = ToolRegistry()
    reg.register_builtin("echo", "echo", {}, {}, lambda args: {"value": args.get("target")})
    return reg


def test_transitive_dependents():
    t = Template(id="t", name="T", start="a", stages=[
        Stage(id="a", name="A"),
        Stage(id="b", name="B", depends_on=["a"]),
        Stage(id="c", name="C", depends_on=["b"]),
        Stage(id="d", name="D", depends_on=["a"]),
    ])
    assert transitive_dependents(t, "b") == {"b", "c"}


def test_next_ready_respects_deps_and_condition():
    t = Template(id="t", name="T", start="a", stages=[
        Stage(id="a", name="A"),
        Stage(id="b", name="B", depends_on=["a"], condition={"op": "truthy", "key": "go"}),
    ])
    rs = RunState(run_id="r", template_id="t", target="x",
                  stage_status={"a": "completed", "b": "pending"}, facts={"go": True})
    assert next_ready(t, rs) == ["b"]


def test_run_follows_dependency_order_and_checkpoints(tmp_path):
    template = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="first")]),
        Stage(id="b", name="b", depends_on=["a"], tools=[ToolBinding(tool="echo", key="second")]),
    ])
    log = EventLog(tmp_path / "s.jsonl")
    checkpoint = tmp_path / "state.json"
    rs = Executor(template, _registry(), log, run_id="r1", checkpoint_path=checkpoint).run("example.com")
    assert rs.facts["first"] == {"value": "example.com"}
    assert rs.facts["second"] == {"value": "example.com"}
    assert rs.stage_status == {"a": COMPLETED, "b": COMPLETED}
    saved = load_run_state(checkpoint)
    assert saved.run_id == "r1"
    assert saved.stage_status == rs.stage_status
    assert saved.checkpoint_version >= 2


def test_condition_skips_stage(tmp_path):
    template = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="a"),
        Stage(id="b", name="b", depends_on=["a"], condition={"op": "truthy", "key": "go"}),
    ])
    log = EventLog(tmp_path / "s.jsonl")
    rs = Executor(template, _registry(), log, run_id="r").run("example.com")
    assert rs.stage_status == {"a": COMPLETED, "b": SKIPPED}
    assert [e.data["stage"] for e in log.read() if e.type == "stage_finished" and e.data.get("reason") == "condition_false"] == ["b"]


def test_failed_dependency_skips_downstream(tmp_path):
    template = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out")],
              gates=[GateRule(name="g", check={"op": "truthy", "key": "nope"}, on_fail="block")]),
        Stage(id="b", name="b", depends_on=["a"]),
        Stage(id="c", name="c", depends_on=["b"]),
    ])
    log = EventLog(tmp_path / "s.jsonl")
    rs = Executor(template, _registry(), log, run_id="r").run("example.com")
    assert rs.stage_status == {"a": FAILED, "b": SKIPPED, "c": COMPLETED}
    assert [e.data["stage"] for e in log.read() if e.type == "stage_finished" and e.data.get("reason") == "dependency_failed"] == ["b"]


def test_gate_block_marks_failed(tmp_path):
    template = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out")],
              gates=[GateRule(name="has_data", check={"op": "truthy", "key": "nope"}, on_fail="block")]),
    ])
    log = EventLog(tmp_path / "s.jsonl")
    rs = Executor(template, _registry(), log, run_id="r").run("example.com")
    assert rs.stage_status["a"] == FAILED
    assert [e.type for e in log.read() if e.type == "gate_block"]


def test_gate_warn_does_not_block(tmp_path):
    template = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out")],
              gates=[GateRule(name="has_data", check={"op": "truthy", "key": "nope"}, on_fail="warn")]),
    ])
    log = EventLog(tmp_path / "s.jsonl")
    rs = Executor(template, _registry(), log, run_id="r").run("example.com")
    assert rs.stage_status["a"] == COMPLETED
    assert [e.type for e in log.read() if e.type == "gate_warn"]


def test_skip_jump_revisit(tmp_path):
    template = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="a"),
        Stage(id="b", name="b", depends_on=["a"]),
        Stage(id="c", name="c", depends_on=["b"]),
    ])
    ex = Executor(template, _registry(), EventLog(tmp_path / "s.jsonl"), run_id="r")
    rs = ex.run("x")
    assert rs.stage_status == {"a": COMPLETED, "b": COMPLETED, "c": COMPLETED}
    rs = ex.skip_stage(rs, "b")
    assert rs.stage_status["b"] == SKIPPED
    rs = ex.jump_to(rs, "a")
    assert rs.stage_status["a"] == READY
    dependents = ex.revisit_stage(rs, "b")
    assert dependents == {"b", "c"}
    assert rs.stage_status["b"] == PENDING
    assert rs.stage_status["c"] == PENDING


def test_resume_from_checkpoint_reruns_only_pending(tmp_path):
    template = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="first")]),
        Stage(id="b", name="b", depends_on=["a"], tools=[ToolBinding(tool="echo", key="second")]),
    ])
    log = EventLog(tmp_path / "s.jsonl")
    checkpoint = tmp_path / "state.json"
    ex = Executor(template, _registry(), log, run_id="r", checkpoint_path=checkpoint)
    rs = ex.run("example.com")
    loaded = load_run_state(checkpoint)
    # mark b for re-run; a stays completed
    ex.revisit_stage(loaded, "b")
    events_before = len(log.read())
    rs2 = ex.run("example.com", run_state=loaded)
    assert rs2.stage_status["a"] == COMPLETED
    assert rs2.stage_status["b"] == COMPLETED
    rerun_starts = [e for e in log.read()[events_before:] if e.type == "stage_started"]
    assert [e.data["stage"] for e in rerun_starts] == ["b"]


def test_run_state_roundtrip_file(tmp_path):
    rs = RunState(run_id="r", template_id="t", target="x", stage_status={"a": COMPLETED}, facts={"a": 1})
    path = tmp_path / "s.json"
    save_run_state(rs, path)
    loaded = load_run_state(path)
    assert loaded.run_id == "r"
    assert loaded.stage_status == {"a": COMPLETED}
    assert loaded.checkpoint_version == 1
