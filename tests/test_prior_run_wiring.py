import time

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
    def __init__(self):
        self.responses = [{"content": "[]", "tool_calls": []}]

    def chat(self, messages, tools=None):
        return self.responses.pop(0)


_TPL = {
    "id": "t1",
    "name": "demo",
    "version": 1,
    "start": "a",
    "stages": [{"id": "a", "name": "A", "depends_on": []}],
    "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    "skills": [],
}


def _seed_prior_run(run_id, created_at):
    rt._active().runs[run_id] = {
        "id": run_id,
        "template_id": "t1",
        "target": "x",
        "created_at": created_at,
        "events": [{"type": "gate_block", "data": {"stage": "a", "gate": "has_data"}}],
    }
    rt._active().save_finding(f"f_{run_id}", {
        "id": f"f_{run_id}",
        "run_id": run_id,
        "title": "A",
        "status": "false_positive",
        "dedup_key": "k1",
        "target": "x",
        "severity": "high",
        "confidence": "medium",
    })


def _start_and_wait(monkeypatch, captured, payload):
    fp_captured = {}

    def fake_execute(template, provider, target, autonomous, **kwargs):
        captured["prior_context"] = kwargs.get("prior_context")
        return {}, [], "# Report", {}

    def fake_findings(provider, facts, template, target="", known_false_positives=None):
        fp_captured["kfp"] = known_false_positives
        return []

    monkeypatch.setattr(rt, "_execute_run", fake_execute)
    monkeypatch.setattr(rt, "generate_findings", fake_findings)
    monkeypatch.setattr(rt, "_get_provider", lambda: _FakeProvider())
    started = client.post("/api/runs", json=payload)
    assert started.status_code == 200
    run_id = started.json()["id"]
    for _ in range(200):
        if captured.get("prior_context") is not None and "kfp" in fp_captured:
            break
        time.sleep(0.05)
    return run_id, fp_captured


def test_prior_run_wiring_injects_context(monkeypatch):
    rt._template_store.save("t1", _TPL)
    _seed_prior_run("r0", "2026-08-29T00:00:00")
    captured = {}
    _, fp_captured = _start_and_wait(
        monkeypatch,
        captured,
        {"template": _TPL, "target": "example.com", "prior_run_id": "r0"},
    )
    ctx = captured["prior_context"]
    assert ctx is not None
    assert ctx["prior_run_id"] == "r0"
    assert ctx["known_false_positives"] == ["k1"]
    assert ctx["prior_gate_results"][0]["gate"] == "has_data"
    assert fp_captured["kfp"] == ["k1"]


def test_prior_run_defaults_to_latest_for_template(monkeypatch):
    rt._template_store.save("t1", _TPL)
    _seed_prior_run("r-old", "2026-08-29T00:00:00")
    _seed_prior_run("r-new", "2026-08-29T01:00:00")
    captured = {}
    _start_and_wait(monkeypatch, captured, {"template": _TPL, "target": "example.com"})
    assert captured["prior_context"]["prior_run_id"] == "r-new"
