import threading
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


def _template():
    return {
        "id": "t1",
        "name": "demo",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }


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


def test_run_and_evidence_scoped_by_session(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    cid = client.post("/api/conversations", json={"kind": "task", "name": "t"}).json()["id"]
    r = client.post("/api/run", json={"template": _template(), "target": "example.com", "session_id": cid})
    assert r.status_code == 200
    run_id = r.json()["id"]
    assert run_id in [x["id"] for x in client.get("/api/runs", params={"session_id": cid}).json()["runs"]]
    assert client.get("/api/runs", params={"session_id": "conv_other"}).json()["runs"] == []
    stored = client.get(f"/api/runs/{run_id}").json()
    assert stored.get("session_id") == cid
    evs = client.get("/api/evidence", params={"session_id": cid}).json()["evidence"]
    assert len(evs) > 0
    assert all(e.get("session_id") == cid for e in evs)
    assert client.get("/api/evidence", params={"session_id": "conv_other"}).json()["evidence"] == []


def test_findings_and_assets_scoped_by_session():
    rt._active().save_finding("f1", {"id": "f1", "title": "a", "session_id": "s1"})
    rt._active().save_finding("f2", {"id": "f2", "title": "b", "session_id": "s2"})
    assert [f["id"] for f in client.get("/api/findings", params={"session_id": "s1"}).json()["findings"]] == ["f1"]
    assert [f["id"] for f in client.get("/api/findings", params={"session_id": "s2"}).json()["findings"]] == ["f2"]

    rt._active().assets.upsert_asset(kind="domain", value="a.com", session_id="s1")
    rt._active().assets.upsert_asset(kind="domain", value="b.com", session_id="s2")
    assert [a["value"] for a in client.get("/api/assets", params={"session_id": "s1"}).json()["assets"]] == ["a.com"]
    assert [a["value"] for a in client.get("/api/assets", params={"session_id": "s2"}).json()["assets"]] == ["b.com"]


def test_stop_endpoint(monkeypatch):
    release = threading.Event()

    class BlockingProvider:
        def stream_chat(self, messages, tools):
            yield {"type": "delta", "content": "thinking"}
            release.wait(timeout=10)
            yield {"type": "done", "content": "done", "tool_calls": []}

        def chat(self, messages, tools):
            return {"content": "done", "tool_calls": []}

    monkeypatch.setattr(rt, "_get_provider", lambda: BlockingProvider())
    cid = client.post("/api/conversations", json={"kind": "task", "name": "t"}).json()["id"]
    started = client.post("/api/runs", json={"template": _template(), "target": "example.com", "session_id": cid})
    assert started.status_code == 200
    run_id = started.json()["id"]
    for _ in range(200):
        if server._get_live(run_id) is not None:
            break
        time.sleep(0.02)
    assert server._get_live(run_id) is not None
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 200
    release.set()
    for _ in range(200):
        if server._get_live(run_id) is None:
            break
        time.sleep(0.02)
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json().get("status") == "stopped"


def test_task_conversation_writeback(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    cid = client.post("/api/conversations", json={"kind": "task", "name": "t"}).json()["id"]
    started = client.post("/api/runs", json={"template": _template(), "target": "example.com", "session_id": cid})
    assert started.status_code == 200
    run_id = started.json()["id"]
    for _ in range(200):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail.get("report") is not None:
            break
        time.sleep(0.05)
    assert client.get(f"/api/runs/{run_id}").json().get("session_id") == cid
    conv = next(c for c in client.get("/api/conversations").json()["conversations"] if c["id"] == cid)
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][0]["content"] == "example.com"
    assert conv["messages"][1]["content"]


def test_start_run_unknown_session_404(monkeypatch):
    monkeypatch.setattr(rt, "_get_provider", lambda: _FakeProvider([]))
    started = client.post("/api/runs", json={"template": _template(), "target": "x", "session_id": "nope"})
    assert started.status_code == 404
