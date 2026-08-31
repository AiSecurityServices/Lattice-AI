import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from lattice_ai import approval
from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.approval import (
    bind_store,
    create_pending,
    expire_run_pending,
    get_pending,
    resolve_pending,
    wait_pending,
)
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.tools import ApprovalDenied
from lattice_ai.workspace import ProjectStore


@pytest.fixture
def project(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    bind_store(store.active().approvals)
    yield store


def test_record_persists_across_reopen(tmp_path):
    ProjectStore(tmp_path / "projects")
    aid = create_pending("nmap", {"target": "example.com"})
    # Simulate a server restart: rebuild every store from disk and rebind.
    reopened = ProjectStore(tmp_path / "projects")
    bind_store(reopened.active().approvals)
    assert get_pending(aid)["status"] == "pending"
    resolved = resolve_pending(aid, True, reason="ok")
    assert resolved["status"] == "approved"
    assert reopened.active().approvals[aid]["status"] == "approved"


def test_denied_decision_is_audited(project):
    aid = create_pending("sqlmap", {"target": "example.com"})
    resolve_pending(aid, False, reason="out of engagement scope")
    record = project.active().approvals[aid]
    assert record["status"] == "denied"
    assert record["reason"] == "out of engagement scope"
    assert record["resolved_at"]


def test_args_are_redacted_in_store_but_raw_in_process(project):
    tool = {"name": "http_api", "secret_fields": ["headers.authorization"]}
    aid = create_pending("http_api", {"target": "example.com", "password": "hunter2", "q": "ok"}, tool=tool)
    stored = project.active().approvals[aid]
    assert stored["args_redacted"]["password"] == "[REDACTED]"
    assert stored["args_redacted"]["q"] == "ok"
    pending = get_pending(aid)
    assert pending["args"]["password"] == "hunter2"
    assert pending["tool_payload"] == tool


def test_ttl_expiry_marks_record_and_blocks_resolve(project, monkeypatch):
    monkeypatch.setattr(approval, "DEFAULT_TTL_SECONDS", 0.1)
    aid = create_pending("nmap", {"target": "example.com"})
    time.sleep(0.25)
    assert get_pending(aid)["status"] == "expired"
    with pytest.raises(KeyError):
        resolve_pending(aid, True)
    with pytest.raises(ApprovalDenied):
        wait_pending(aid, timeout=0.2)


def test_wait_pending_returns_when_approved_and_raises_when_denied(project):
    aid = create_pending("nmap", {"target": "example.com"})
    resolve_pending(aid, True)
    assert wait_pending(aid, timeout=1)["status"] == "approved"

    denied = create_pending("nmap", {"target": "example.com"})
    resolve_pending(denied, False, reason="no")
    with pytest.raises(ApprovalDenied):
        wait_pending(denied, timeout=1)


def test_wait_pending_timeout_on_still_pending(project):
    aid = create_pending("nmap", {"target": "example.com"})
    with pytest.raises(ApprovalDenied):
        wait_pending(aid, timeout=0.05)


def test_expire_run_pending_expires_only_that_run(project):
    store = project.active().approvals
    first = create_pending("nmap", {"target": "a.com"})
    second = create_pending("nmap", {"target": "b.com"})
    for aid, run_id in ((first, "r1"), (second, "r2")):
        record = store[aid]
        record["run_id"] = run_id
        store[aid] = record
    assert expire_run_pending("r1") == 1
    assert store[first]["status"] == "expired"
    assert store[second]["status"] == "pending"
    assert expire_run_pending("") == 0


def test_memory_fallback_without_bound_store():
    bind_store(None)
    try:
        aid = create_pending("nmap", {"target": "example.com"})
        assert get_pending(aid)["status"] == "pending"
        resolve_pending(aid, True)
        assert get_pending(aid)["status"] == "approved"
    finally:
        bind_store(None)


def test_first_request_is_approval_create_persists_to_project_db(tmp_path, monkeypatch):
    """Cold start regression: the approvals endpoints must force the lazy
    project store before touching the approval module, or the very first
    approval lands in the in-memory fallback instead of SQLite."""
    holder = {}

    def lazy_store():
        if "store" not in holder:
            holder["store"] = ProjectStore(tmp_path / "projects")
        return holder["store"]

    monkeypatch.setattr(rt, "_projects_store", lazy_store)
    client = TestClient(server.app)

    response = client.post("/api/approvals", json={"tool": "scan_port", "args": {"target": "example.com"}})
    assert response.status_code == 200
    approval_id = response.json()["approval_id"]

    project = holder["store"].active()
    assert approval_id in project.approvals
    with sqlite3.connect(project.root / "project.db") as conn:
        (rows,) = conn.execute("SELECT COUNT(*) FROM approvals").fetchone()
    assert rows == 1

    # Resolve and list endpoints work on the same cold store binding.
    resolved = client.post(f"/api/approvals/{approval_id}/resolve", json={"approved": True, "reason": "ok"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "approved"
    assert client.get("/api/approvals").status_code == 200

    # A restart over the same project root still finds the record.
    bind_store(ProjectStore(tmp_path / "projects").active().approvals)
    assert get_pending(approval_id)["status"] == "approved"


def test_record_carries_audit_fields(project):
    tool = {"name": "sqlmap", "description": "Test and exploit SQL injection",
            "command": ["sqlmap", "-u", "{target}"]}
    aid = create_pending("sqlmap", {"target": "http://example.com/item?id=1 --dump"}, tool=tool)
    record = project.active().approvals[aid]
    assert record["tool"] == "sqlmap"
    assert record["status"] == "pending"
    assert record["created_at"]
    assert record["expires_at"] > time.time()
    assert record["category"] == "data-exfil"
    assert record["rule_id"] == "sqlmap-dump"


def test_approval_with_tool_payload_runs_trial_without_llm(tmp_path, monkeypatch):
    """Decoupled trial flow: POST /api/approvals can carry the tool payload, so
    resolve → /api/tools/try/execute works with no LLM provider at all."""
    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    store = ProjectStore(tmp_path / "projects")
    monkeypatch.setattr(rt, "_template_store", template_store)
    monkeypatch.setattr(rt, "_tool_store", tool_store)
    monkeypatch.setattr(rt, "_skill_store", skill_store)
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    monkeypatch.setattr(rt, "_get_provider", lambda: None)

    client = TestClient(server.app)
    tool_payload = {"name": "echo", "description": "echo", "runner": "builtin"}
    created = client.post("/api/approvals", json={
        "tool": "echo",
        "args": {"target": "example.com"},
        "tool_payload": tool_payload,
    })
    assert created.status_code == 200
    approval_id = created.json()["approval_id"]

    assert client.post(f"/api/approvals/{approval_id}/resolve", json={"approved": True}).status_code == 200

    executed = client.post("/api/tools/try/execute", json={"approval_id": approval_id})
    assert executed.status_code == 200
    body = executed.json()
    assert body["tool"] == "echo"
    assert isinstance(body["result"], dict)
    assert body["findings"] == []  # LLM niceties skipped, execution result intact

    # the approval record keeps the payload for audit
    assert store.active().approvals[approval_id]["tool"] == "echo"


def test_approval_tool_payload_roundtrip_via_get_pending(tmp_path, monkeypatch):
    """T4.3 contract: create with payload → resolve → get_pending exposes
    tool_payload (and the tool-as-dict shorthand is accepted)."""
    store = ProjectStore(tmp_path / "projects")
    bind_store(store.active().approvals)
    tool_payload = {"name": "http_api", "runner": "builtin"}

    aid = None
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    client = TestClient(server.app)
    created = client.post("/api/approvals", json={
        "tool_name": "http_api",
        "tool": tool_payload,  # dict shorthand per the M3-B contract
        "args": {"target": "example.com"},
    })
    assert created.status_code == 200
    aid = created.json()["approval_id"]
    client.post(f"/api/approvals/{aid}/resolve", json={"approved": True})

    pending = get_pending(aid)
    assert pending["tool_payload"]["name"] == "http_api"
    assert pending["args"]["target"] == "example.com"
    assert store.active().approvals[aid]["tool"] == "http_api"
