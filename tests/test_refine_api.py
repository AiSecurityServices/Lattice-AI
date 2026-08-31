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


def _seed_template():
    tpl = {
        "id": "t1",
        "name": "demo",
        "version": 1,
        "start": "a",
        "stages": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "tools": [],
        "skills": [],
    }
    rt._template_store.save("t1", tpl)
    return tpl


def test_evolution_endpoint():
    rt._active().runs["r1"] = {"id": "r1", "template_id": "t", "target": "x", "evolution": {"summary": "ok"}}
    r = client.get("/api/runs/r1/evolution")
    assert r.status_code == 200
    assert r.json()["evolution"]["summary"] == "ok"
    assert client.get("/api/runs/nope/evolution").status_code == 404


def test_refine_applies_and_bumps_version():
    _seed_template()
    r = client.post("/api/templates/t1/refine", json={"suggestions": [
        {"type": "add_depends_on", "stage_id": "b", "depends_on": "a"},
    ]})
    assert r.status_code == 200
    body = r.json()
    assert body["new_version"] == 2
    assert len(body["applied"]) == 1
    assert body["rejected"] == []
    assert body["template"]["stages"][1]["depends_on"] == ["a"]
    assert rt._template_store.get("t1")["version"] == 2


def test_refine_rejects_cycle_suggestion_but_bumps():
    _seed_template()
    r = client.post("/api/templates/t1/refine", json={"suggestions": [
        {"type": "add_depends_on", "stage_id": "b", "depends_on": "a"},
        {"type": "add_depends_on", "stage_id": "a", "depends_on": "b"},
    ]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["applied"]) == 1
    assert len(body["rejected"]) == 1
    assert "cycle" in body["rejected"][0]["reason"]
    assert body["new_version"] == 2


def test_refine_rejects_missing_stage():
    _seed_template()
    r = client.post("/api/templates/t1/refine", json={"suggestions": [
        {"type": "add_tool", "stage_id": "zzz", "tool_name": "nmap"},
    ]})
    body = r.json()
    assert body["rejected"] and "stage not found" in body["rejected"][0]["reason"]


def test_history_and_rollback():
    _seed_template()
    rt._template_store.save_versioned("t1", {
        "id": "t1", "name": "demo", "version": 1, "start": "a",
        "stages": [{"id": "a", "name": "A"}, {"id": "b", "name": "B", "depends_on": ["a"]}],
        "tools": [],
    })
    h = client.get("/api/templates/t1/history")
    assert h.status_code == 200
    assert h.json()["versions"] == [1]
    r = client.post("/api/templates/t1/rollback/1")
    assert r.status_code == 200
    assert r.json()["new_version"] == 3
    assert client.post("/api/templates/t1/rollback/99").status_code == 404
