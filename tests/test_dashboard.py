import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.workspace import ProjectStore


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "projects")
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    yield store


client = TestClient(server.app)


def test_dashboard_empty(isolated_store):
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert len(body["days"]) == 7
    assert all(k in body["kpis"] for k in ("assets", "subdomains", "findings", "runs"))
    for kpi in body["kpis"].values():
        assert kpi["total"] == 0
        assert len(kpi["spark"]) == 7
    assert body["recent_runs"] == []
    assert body["recent_findings"] == []


def test_dashboard_counts_and_feeds(isolated_store):
    project = rt._active()
    project.save_run("run1", {
        "id": "run1",
        "template_id": "demo",
        "target": "example.com",
        "kind": "run",
        "session_id": "conv1",
        "created_at": "2026-08-30T10:00:00",
        "facts": {},
        "events": [],
    })
    project.save_finding("f1", {
        "id": "f1",
        "title": "SQL 注入",
        "severity": "critical",
        "status": "pending",
        "target": "example.com",
        "run_id": "run1",
        "session_id": "conv1",
    })
    project.assets.upsert_asset(kind="subdomain", value="a.example.com", session_id="conv1")
    project.assets.upsert_asset(kind="domain", value="example.com", session_id="conv1")

    res = client.get("/api/dashboard", params={"session_id": "conv1"})
    assert res.status_code == 200
    body = res.json()
    assert body["kpis"]["runs"]["total"] == 1
    assert body["kpis"]["assets"]["total"] == 2
    assert body["kpis"]["subdomains"]["total"] == 1
    findings_kpi = body["kpis"]["findings"]
    assert findings_kpi["total"] == 1
    assert findings_kpi["severity"]["critical"] == 1
    assert body["recent_runs"][0]["id"] == "run1"
    assert body["recent_findings"][0]["title"] == "SQL 注入"
    assert body["recent_findings"][0]["created_at"] == "2026-08-30T10:00:00"

    other = client.get("/api/dashboard", params={"session_id": "conv2"})
    assert other.json()["kpis"]["runs"]["total"] == 0


def test_dashboard_days_param(isolated_store):
    res = client.get("/api/dashboard", params={"days": 3})
    assert res.status_code == 200
    assert len(res.json()["days"]) == 3
    assert client.get("/api/dashboard", params={"days": 0}).status_code == 422
