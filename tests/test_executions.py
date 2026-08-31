"""M3-A E1: stage_executions records — row writes, budget diffs, query filters."""
import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.budget import BudgetTracker
from lattice_ai.builtins import install_builtins
from lattice_ai.db import connect
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.models import Template, from_dict
from lattice_ai.tools import ToolRegistry
from lattice_ai.workspace import ProjectStore


@pytest.fixture()
def exec_env(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "projects")
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    executions = store.active().executions

    def make_executor(template, run_id="r1", budget=None):
        registry = ToolRegistry()
        install_builtins(registry)
        log = EventLog(tmp_path / f"{run_id}.jsonl")
        return Executor(template, registry, log, run_id=run_id, budget=budget, exec_store=executions)

    def make_template(**stage_overrides):
        """a -> b -> c chain of echo stages; overrides merge per-stage dicts."""
        stages = [
            {"id": "a", "name": "A", "tools": [{"tool": "echo", "key": "a", "defaults": {"msg": "x"}}]},
            {"id": "b", "name": "B", "depends_on": ["a"], "tools": [{"tool": "echo", "key": "b", "defaults": {"msg": "y"}}]},
            {"id": "c", "name": "C", "depends_on": ["b"], "tools": [{"tool": "echo", "key": "c", "defaults": {"msg": "z"}}]},
        ]
        for stage in stages:
            stage.update(stage_overrides.get(stage["id"], {}))
        return from_dict(Template, {"id": "t", "name": "T", "start": "a", "stages": stages, "tools": []})

    return store, executions, make_executor, make_template


class _UsageAgent:
    """Minimal StageAgent stand-in that burns LLM usage into the shared tracker."""

    def __init__(self):
        self.budget = None

    def run_stage(self, stage, target, facts, *, cwd=None, secret_paths=None, approver=None):
        self.budget.add_usage({"prompt_tokens": 120, "completion_tokens": 80})
        return facts


def test_rows_written_per_stage_with_zero_llm_diffs(exec_env, tmp_path):
    _, executions, make_executor, make_template = exec_env
    template = make_template()
    rs = make_executor(template, run_id="run-a").run("example.com")
    assert set(rs.stage_status.values()) == {"completed"}

    keys = {"run-a:a", "run-a:b", "run-a:c"}
    assert keys <= set(executions)
    for key in sorted(keys):
        row = executions[key]
        assert row["status"] == "completed"
        assert row["started_at"] and row["finished_at"]
        assert isinstance(row["elapsed_ms"], int) and row["elapsed_ms"] >= 0
        assert row["tool_calls"] == 1  # one echo binding per stage
        assert row["llm_calls"] == 0 and row["tokens_in"] == 0 and row["tokens_out"] == 0
        assert row["error"] == ""


def test_llm_and_token_diffs_come_from_stage_scoped_snapshots(exec_env):
    _, executions, make_executor, make_template = exec_env
    agent = _UsageAgent()
    template = make_template()
    rs = make_executor(template, run_id="run-b", budget=BudgetTracker()).run("example.com", agent=agent)
    assert set(rs.stage_status.values()) == {"completed"}
    for key in ("run-b:a", "run-b:b", "run-b:c"):
        row = executions[key]
        assert row["llm_calls"] == 1  # one add_usage per stage, not cumulative
        assert row["tokens_in"] == 120
        assert row["tokens_out"] == 80


def test_gate_block_marks_failed_and_downstream_skipped(exec_env):
    _, executions, make_executor, make_template = exec_env
    template = make_template(**{
        "a": {"gates": [{"name": "never", "check": {"op": "equals", "key": "a.value", "value": "nope"}, "on_fail": "block"}]},
    })
    rs = make_executor(template, run_id="run-c").run("example.com")
    assert rs.stage_status["a"] == "failed"
    failed = executions["run-c:a"]
    assert failed["status"] == "failed"
    assert "gate blocked: never" in failed["error"]
    assert failed["tool_calls"] == 1  # the stage really ran its tools
    failed_child = executions["run-c:b"]
    assert failed_child["status"] == "skipped"
    assert failed_child["error"] == "dependency_failed"
    assert failed_child["tool_calls"] == 0
    # a skipped dependency counts as settled, so c still runs (existing semantics)
    assert executions["run-c:c"]["status"] == "completed"


def test_condition_false_skip_records_reason(exec_env):
    _, executions, make_executor, make_template = exec_env
    template = make_template(**{"b": {"condition": {"op": "equals", "key": "a.value", "value": "never"}}})
    make_executor(template, run_id="run-d").run("example.com")
    assert executions["run-d:b"]["status"] == "skipped"
    assert executions["run-d:b"]["error"] == "condition_false"
    assert executions["run-d:c"]["status"] == "completed"


def test_exec_store_absent_keeps_executor_working(exec_env, tmp_path):
    registry = ToolRegistry()
    install_builtins(registry)
    template = from_dict(Template, {
        "id": "t", "name": "T", "start": "a",
        "stages": [{"id": "a", "name": "A", "tools": [{"tool": "echo", "key": "a"}]}],
        "tools": [],
    })
    log = EventLog(tmp_path / "plain.jsonl")
    rs = Executor(template, registry, log, run_id="plain").run("example.com")
    assert rs.stage_status["a"] == "completed"


# ---- routes ----

@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "projects")
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    monkeypatch.setattr(rt, "_template_store", __import__("lattice_ai.library", fromlist=["TemplateStore"]).TemplateStore(tmp_path / "templates"))
    return store


client = TestClient(server.app)


def _seed_run(project, run_id, stage_ids):
    project.save_run(run_id, {"id": run_id, "template_id": "tpl", "target": "x", "kind": "run", "created_at": "2026-08-30T00:00:00"})
    for index, stage_id in enumerate(stage_ids):
        project.executions[f"{run_id}:{stage_id}"] = {
            "run_id": run_id, "stage_id": stage_id, "status": "completed" if index % 2 == 0 else "failed",
            "started_at": f"2026-08-30T00:0{index}:00", "finished_at": f"2026-08-30T00:0{index}:05",
            "elapsed_ms": 100 + index, "tool_calls": 1, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "error": "",
        }


def test_run_executions_endpoint_orders_by_template_stages(api_env):
    store = api_env
    rt._template_store.save("tpl", {"id": "tpl", "name": "T", "start": "c", "stages": [
        {"id": "c", "name": "C"}, {"id": "a", "name": "A"}, {"id": "b", "name": "B"},
    ], "tools": []})
    _seed_run(store.active(), "run-1", ["a", "b", "c"])
    res = client.get("/api/runs/run-1/executions")
    assert res.status_code == 200
    rows = res.json()["executions"]
    assert [row["stage_id"] for row in rows] == ["c", "a", "b"]  # template order, not write order
    assert client.get("/api/runs/missing/executions").status_code == 404


def test_list_executions_filters_status_and_paginates(api_env):
    store = api_env
    _seed_run(store.active(), "run-1", ["a", "b"])
    _seed_run(store.active(), "run-2", ["a", "b"])
    res = client.get("/api/executions", params={"status": "completed"})
    body = res.json()
    assert body["total"] == 2
    assert all(row["status"] == "completed" for row in body["executions"])

    multi = client.get("/api/executions", params={"status": "completed,failed"})
    assert multi.json()["total"] == 4

    paged = client.get("/api/executions", params={"limit": 1, "offset": 1})
    assert len(paged.json()["executions"]) == 1
    assert paged.json()["total"] == 4

    empty = client.get("/api/executions", params={"status": "running"})
    assert empty.json()["executions"] == [] and empty.json()["total"] == 0


def test_execution_rows_are_sqlite_backed_and_persist(api_env):
    from lattice_ai.db import JsonStore

    store = api_env
    _seed_run(store.active(), "run-1", ["a"])
    # a fresh connection on the same project db sees the rows (WAL persistence)
    reopened = JsonStore(connect(store.active().root / "project.db"), "stage_executions")
    assert "run-1:a" in reopened


def test_matrix_template_run_records_one_row_per_stage(exec_env, monkeypatch):
    """Acceptance #1 end-to-end: a matrix template run produces exactly one
    execution row per stage with status/elapsed/tokens populated."""
    import urllib.error
    from lattice_ai import builtins as B
    from lattice_ai import builtin_templates as bt

    def _offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(B, "_fetch", _offline)
    monkeypatch.setattr(B, "_crt_sh", _offline)
    monkeypatch.setattr(B, "_hackertarget", _offline)
    monkeypatch.setattr(B, "_dns_brute", _offline)

    _, executions, make_executor, _ = exec_env
    template_dict = next(t for t in bt.MATRIX_TEMPLATES if t["id"] == "matrix-triage-quick")
    template = from_dict(Template, template_dict)
    rs = make_executor(template, run_id="mx1").run("127.0.0.1")

    assert len(template.stages) == 3
    rows = [executions[f"mx1:{stage.id}"] for stage in template.stages]
    assert all(row["run_id"] == "mx1" for row in rows)
    assert [row["stage_id"] for row in rows] == ["probe", "ports", "fingerprint"]
    for row in rows:
        assert row["status"] in ("completed", "skipped", "failed")
        assert isinstance(row["elapsed_ms"], int)
        assert row["started_at"] != ""
        assert row["tool_calls"] >= 1
        assert row["llm_calls"] == 0 and row["tokens_in"] == 0 and row["tokens_out"] == 0
