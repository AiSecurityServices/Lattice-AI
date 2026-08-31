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


_TPL = {
    "id": "t1",
    "name": "demo",
    "start": "a",
    "stages": [
        {"id": "a", "name": "A", "depends_on": [], "tools": [{"tool": "echo", "key": "a", "defaults": {"msg": "a"}}]},
        {"id": "b", "name": "B", "depends_on": ["a"], "tools": [{"tool": "echo", "key": "b", "defaults": {"msg": "b"}}]},
    ],
    "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
}


def _run_to_completion(monkeypatch):
    rt._template_store.save(_TPL["id"], _TPL)
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    started = client.post("/api/runs", json={"template": _TPL, "target": "example.com"})
    assert started.status_code == 200
    run_id = started.json()["id"]
    for _ in range(200):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail.get("report") is not None:
            break
        time.sleep(0.05)
    assert detail.get("report") is not None
    return run_id


def test_workflow_state_endpoint(monkeypatch):
    run_id = _run_to_completion(monkeypatch)
    r = client.get(f"/api/runs/{run_id}/workflow-state")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == run_id
    assert body["stage_status"]["a"] == "completed"
    assert body["stage_status"]["b"] == "completed"
    assert client.get("/api/runs/nope/workflow-state").status_code == 404


def test_control_requires_confirm(monkeypatch):
    run_id = _run_to_completion(monkeypatch)
    r = client.post(f"/api/runs/{run_id}/control", json={"action": "jump", "stage_id": "a"})
    assert r.status_code == 400


def test_control_skip_jump_revisit(monkeypatch):
    run_id = _run_to_completion(monkeypatch)
    skip = client.post(f"/api/runs/{run_id}/control", json={"action": "skip", "stage_id": "b", "confirm": True})
    assert skip.status_code == 200
    assert skip.json()["stage_status"]["b"] == "skipped"
    jump = client.post(f"/api/runs/{run_id}/control", json={"action": "jump", "stage_id": "a", "confirm": True})
    assert jump.status_code == 200
    assert jump.json()["stage_status"]["a"] == "ready"
    revisit = client.post(f"/api/runs/{run_id}/control", json={"action": "revisit", "stage_id": "b", "confirm": True})
    assert revisit.status_code == 200
    assert revisit.json()["stage_status"]["b"] == "pending"
    assert client.post(f"/api/runs/{run_id}/control", json={"action": "revisit", "stage_id": "x", "confirm": True}).status_code == 404


def test_control_resume(monkeypatch):
    run_id = _run_to_completion(monkeypatch)
    client.post(f"/api/runs/{run_id}/control", json={"action": "revisit", "stage_id": "b", "confirm": True})
    r = client.post(f"/api/runs/{run_id}/control", json={"action": "resume", "confirm": True})
    assert r.status_code == 200
    assert r.json()["status"] == "started"
    for _ in range(200):
        state = client.get(f"/api/runs/{run_id}/workflow-state").json()
        if state["stage_status"]["b"] == "completed":
            break
        time.sleep(0.05)
    assert state["stage_status"]["b"] == "completed"
