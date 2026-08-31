import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.workspace import ProjectStore


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    store = ProjectStore(tmp_path / "projects")
    monkeypatch.setattr(rt, "_template_store", template_store)
    monkeypatch.setattr(rt, "_tool_store", tool_store)
    monkeypatch.setattr(rt, "_skill_store", skill_store)
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    yield


client = TestClient(server.app)


def _put_template(template_id="t1", name="模板一"):
    template = {
        "id": template_id,
        "name": name,
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out"}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    r = client.put(f"/api/templates/{template_id}", json=template)
    assert r.status_code == 200
    return template


def _add_stage_suggestion(stage_name="new-stage"):
    return {"type": "add_stage", "stage_name": stage_name, "detail": "补充阶段"}


def test_refine_creates_lineage_snapshot():
    _put_template()
    r = client.post("/api/templates/t1/refine", json={"suggestions": [_add_stage_suggestion()]})
    assert r.status_code == 200
    assert r.json()["new_version"] == 2

    versions = client.get("/api/templates/t1/versions").json()
    assert versions["total"] == 2
    by_version = {v["version"]: v for v in versions["versions"]}
    assert by_version[2]["lineage"]["source"] == "refine"
    assert by_version[2]["current"] is True
    assert by_version[1]["lineage"]["source"] == "manual"


def test_apply_suggestion_creates_selfcheck_lineage_snapshot():
    _put_template()
    r = client.post("/api/workflow/apply-suggestion", json={
        "template_id": "t1",
        "suggestion": _add_stage_suggestion(),
        "ref_id": "run-123",
    })
    assert r.status_code == 200
    assert r.json()["new_version"] == 2

    versions = client.get("/api/templates/t1/versions").json()
    by_version = {v["version"]: v for v in versions["versions"]}
    assert by_version[2]["lineage"] == {"source": "selfcheck", "ref_id": "run-123"}


def test_rollback_returns_new_version_and_keeps_chain():
    _put_template()
    client.post("/api/templates/t1/refine", json={"suggestions": [_add_stage_suggestion("stage-two")]})
    r = client.post("/api/templates/t1/rollback/1")
    assert r.status_code == 200
    body = r.json()
    assert body["new_version"] == 3  # a copy, not an in-place overwrite
    assert body["deprecation"]
    restored = body["template"]
    assert restored["version"] == 3
    assert all(s["id"] != "stage-two" for s in restored["stages"])

    # Chain is intact: v1, v2 still retrievable, current is v3.
    versions = client.get("/api/templates/t1/versions").json()
    assert [v["version"] for v in versions["versions"]] == [1, 2, 3]
    v2 = client.get("/api/templates/t1/versions/2").json()
    assert any(s["id"] == "stage-two" for s in v2["template"]["stages"])


def test_double_rollback_never_breaks_the_chain():
    _put_template()
    client.post("/api/templates/t1/refine", json={"suggestions": [_add_stage_suggestion("stage-two")]})
    first = client.post("/api/templates/t1/rollback/1").json()
    second = client.post("/api/templates/t1/rollback/1").json()
    assert (first["new_version"], second["new_version"]) == (3, 4)

    versions = client.get("/api/templates/t1/versions").json()
    assert [v["version"] for v in versions["versions"]] == [1, 2, 3, 4]
    for v in (1, 2, 3, 4):
        assert client.get(f"/api/templates/t1/versions/{v}").status_code == 200
    assert client.get("/api/templates/t1/versions/4").json()["template"]["stages"][0]["id"] == "a"


def test_restore_endpoint_is_the_new_semantics():
    _put_template()
    client.post("/api/templates/t1/refine", json={"suggestions": [_add_stage_suggestion("stage-two")]})
    r = client.post("/api/templates/t1/versions/1/restore")
    assert r.status_code == 200
    assert r.json()["new_version"] == 3


def test_versions_endpoint_paginates():
    _put_template()
    for i in range(3):
        client.post("/api/templates/t1/refine", json={"suggestions": [_add_stage_suggestion(f"s{i}")]})
    page = client.get("/api/templates/t1/versions", params={"offset": 0, "limit": 2}).json()
    assert page["total"] == 4
    assert [v["version"] for v in page["versions"]] == [1, 2]
    page2 = client.get("/api/templates/t1/versions", params={"offset": 2, "limit": 2}).json()
    assert [v["version"] for v in page2["versions"]] == [3, 4]
    assert page2["versions"][-1]["current"] is True


def test_versions_batch_returns_requested_versions():
    _put_template()
    client.post("/api/templates/t1/refine", json={"suggestions": [_add_stage_suggestion("stage-two")]})
    r = client.post("/api/templates/t1/versions/batch", json={"versions": [1, 2, 99]})
    assert r.status_code == 200
    versions = {v["version"] for v in r.json()["versions"]}
    assert versions == {1, 2}


def test_version_endpoints_404_for_missing_template_or_version():
    assert client.get("/api/templates/nope/versions").status_code == 404
    _put_template()
    assert client.get("/api/templates/t1/versions/99").status_code == 404
    assert client.post("/api/templates/t1/versions/99/restore").status_code == 404
    assert client.post("/api/templates/nope/versions/batch", json={"versions": [1]}).status_code == 404


def test_preview_suggestion_diffs_without_saving():
    template = {
        "id": "t1",
        "name": "n",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out"}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    r = client.post("/api/templates/preview-suggestion", json={
        "template": template,
        "suggestion": _add_stage_suggestion("stage-x"),
    })
    assert r.status_code == 200
    updated = r.json()["template"]
    assert any(s["id"] == "stage-x" for s in updated["stages"])
    # nothing persisted
    assert rt._template_store.get("t1") is None

    bad = client.post("/api/templates/preview-suggestion", json={
        "template": template,
        "suggestion": {"type": "remove_stage", "stage_id": "a"},
    })
    assert bad.status_code == 400


def test_evolution_runs_lists_recent_runs_with_suggestions():
    _put_template()
    project = rt._active()
    project.runs["r-old"] = {
        "id": "r-old", "template_id": "t1", "target": "example.com",
        "created_at": "2026-08-29T10:00:00",
        "evolution": {"summary": "s1", "suggestions": [{"type": "add_stage", "stage_name": "x"}]},
    }
    project.runs["r-new"] = {
        "id": "r-new", "template_id": "t1", "target": "example.com",
        "created_at": "2026-08-30T10:00:00",
        "evolution": {"summary": "s2", "suggestions": [{"type": "add_stage"}, {"type": "add_gate"}]},
    }
    project.runs["r-other"] = {"id": "r-other", "template_id": "t1", "created_at": "2026-08-30T11:00:00", "evolution": {"suggestions": []}}
    project.runs["r-noevo"] = {"id": "r-noevo", "template_id": "t1", "created_at": "2026-08-30T12:00:00"}

    runs = client.get("/api/templates/t1/evolution-runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["r-new", "r-old"]
    assert runs[0]["suggestion_count"] == 2
    assert runs[0]["summary"] == "s2"
