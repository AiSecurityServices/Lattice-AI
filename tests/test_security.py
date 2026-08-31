import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.events import EventLog
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.llm import OpenAICompatibleProvider
from lattice_ai.models import Tool, from_dict, to_dict
from lattice_ai.persistence import atomic_write_json, atomic_write_text
from lattice_ai.approval import create_pending, resolve_pending
from lattice_ai.workspace import ProjectStore


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    template_store.save(server._LITE_PENTEST_TEMPLATE["id"], server._LITE_PENTEST_TEMPLATE)
    store = ProjectStore(tmp_path / "projects")
    monkeypatch.setattr(rt, "_template_store", template_store)
    monkeypatch.setattr(rt, "_tool_store", tool_store)
    monkeypatch.setattr(rt, "_skill_store", skill_store)
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    yield


client = TestClient(server.app)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def test_middleware_blocks_foreign_origin():
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403


def test_middleware_allows_loopback_origin_and_plain_clients():
    assert client.get("/health").status_code == 200
    allowed = client.get("/health", headers={"Origin": "http://127.0.0.1:6317"})
    assert allowed.status_code == 200
    via_referer = client.get("/health", headers={"Referer": "http://localhost:6317/run"})
    assert via_referer.status_code == 200


def test_middleware_allows_extra_hosts_via_env(monkeypatch):
    monkeypatch.setenv("LATTICE_ALLOWED_HOSTS", "intranet.corp")
    response = client.get("/health", headers={"Origin": "http://intranet.corp:8742"})
    assert response.status_code == 200


def test_preflight_reports_scope_verdict():
    response = client.put("/api/scope", json={"allow_domains": ["example.com"]})
    assert response.status_code == 200

    inside = client.post(
        "/api/run/preflight",
        json={"template": server._LITE_PENTEST_TEMPLATE, "target": "sub.example.com"},
    )
    assert inside.status_code == 200
    assert inside.json()["scope"]["configured"] is True
    assert inside.json()["scope"]["ok"] is True

    outside = client.post(
        "/api/run/preflight",
        json={"template": server._LITE_PENTEST_TEMPLATE, "target": "evil.example"},
    )
    assert outside.status_code == 200
    assert outside.json()["scope"]["ok"] is False


def test_preflight_flags_restricted_target():
    response = client.post(
        "/api/run/preflight",
        json={"template": server._LITE_PENTEST_TEMPLATE, "target": "198.51.100.7"},
    )
    scope = response.json()["scope"]
    assert scope["restricted"] is True
    assert scope["ok"] is False


def _approved_pending(tool: Tool, args: dict) -> str:
    approval_id = create_pending(tool.name, args, tool=to_dict(tool))
    resolve_pending(approval_id, True)
    return approval_id


def test_trial_execution_enforces_scope():
    client.put("/api/scope", json={"allow_domains": ["example.com"]})
    tool = Tool(
        name="echo",
        description="return the msg argument",
        runner="builtin",
    )
    approval_id = _approved_pending(tool, {"target": "evil.example", "msg": "hi"})
    response = client.post("/api/tools/try/execute", json={"approval_id": approval_id})
    assert response.status_code == 400
    assert "outside scope" in response.json()["detail"]


def test_trial_execution_blocks_deny_under_strict_policy():
    client.put("/api/settings/security", json={"level": "strict", "whitelist": []})
    # A non-builtin name: builtin tools keep their own definition in the
    # registry, so the dangerous pattern must live on an imported tool's description.
    tool = Tool(
        name="cleanup-helper",
        description="cleanup helper running rm -rf",
        runner="cli",
        command=["definitely-missing-exe", "{target}"],
    )
    approval_id = _approved_pending(tool, {"target": "example.com"})
    response = client.post("/api/tools/try/execute", json={"approval_id": approval_id})
    assert response.status_code == 400
    assert "danger" in response.json()["detail"]


def test_trial_execution_runs_when_in_scope():
    client.put("/api/scope", json={"allow_domains": ["example.com"]})
    client.put("/api/settings/security", json={"level": "standard", "whitelist": []})
    tool = Tool(name="echo", description="return the msg argument", runner="builtin")
    approval_id = _approved_pending(tool, {"target": "example.com", "msg": "hi"})
    # findings/report generation needs a provider; the execute path raises 400
    # "LLM not configured" only after the tool ran, so a 400 with that detail
    # still proves the tool execution itself passed scope and danger checks.
    response = client.post("/api/tools/try/execute", json={"approval_id": approval_id})
    assert response.status_code in (200, 400)
    if response.status_code == 400:
        assert "LLM not configured" in response.json()["detail"]


def test_event_log_reads_last_seq_from_tail(tmp_path):
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    for i in range(3000):
        log.append("tick", {"i": i})
    log.flush()  # batched durability: reopen sees flushed seqs
    reopened = EventLog(path)
    assert reopened._seq == 3000
    assert len(reopened.read()) == 3000


def test_event_log_tolerates_torn_final_line(tmp_path):
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append("a", {"x": 1})
    log.append("b", {"x": 2})
    log.flush()
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 3, "type": "c", "dat')  # crash mid-write
    reopened = EventLog(path)
    assert reopened._seq == 2
    assert [e.type for e in reopened.read()] == ["a", "b"]


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "nested" / "data.json"
    atomic_write_json(target, {"a": 1})
    atomic_write_text(target, '{"a": 2}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert list(target.parent.glob("*.tmp")) == []


def test_llm_request_retries_on_503(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("x", 503, "Service Unavailable", {}, io.BytesIO(b""))
        return _FakeResponse(b'{"choices": [{"message": {"content": "ok"}}]}')

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("lattice_ai.llm.time.sleep", lambda s: None)
    provider = OpenAICompatibleProvider("https://api.example.com/v1", "key", "model")
    response = provider.chat([{"role": "user", "content": "hi"}], [])
    assert response["content"] == "ok"
    assert calls["n"] == 3


def test_llm_request_does_not_retry_on_400(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            "x", 400, "Bad Request", {}, io.BytesIO(b'{"error":{"message":"bad"}}')
        )

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("lattice_ai.llm.time.sleep", lambda s: None)
    provider = OpenAICompatibleProvider("https://api.example.com/v1", "key", "model")
    with pytest.raises(ValueError):
        provider.chat([{"role": "user", "content": "hi"}], [])
    # one original attempt + one retry without reasoning params, no 5xx-style retries
    assert calls["n"] == 2


def test_remote_peer_requires_token(monkeypatch):
    monkeypatch.delenv("LATTICE_AUTH_DISABLED", raising=False)
    monkeypatch.setattr(server, "_is_loopback_host", lambda host: False)
    monkeypatch.setattr(server, "_auth_token", lambda: "test-token-123")
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"X-Lattice-Token": "wrong"}).status_code == 401
    assert client.get("/health", headers={"X-Lattice-Token": "test-token-123"}).status_code == 200
    bearer = client.get("/health", headers={"Authorization": "Bearer test-token-123"})
    assert bearer.status_code == 200


def test_loopback_peer_skips_token(monkeypatch):
    monkeypatch.delenv("LATTICE_AUTH_DISABLED", raising=False)
    monkeypatch.setattr(server, "_is_loopback_host", lambda host: True)
    assert client.get("/health").status_code == 200


def test_auth_opt_out_env(monkeypatch):
    monkeypatch.setenv("LATTICE_AUTH_DISABLED", "1")
    monkeypatch.setattr(server, "_is_loopback_host", lambda host: False)
    assert client.get("/health").status_code == 200


def test_auth_token_persists_and_is_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "_DATA_ROOT", tmp_path)
    monkeypatch.delenv("LATTICE_TOKEN", raising=False)
    token1 = server._auth_token()
    token2 = server._auth_token()
    assert token1 and token1 == token2
    stored = json.loads((tmp_path / "auth_token.json").read_text(encoding="utf-8"))
    assert stored["token"] == token1


def test_auth_token_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "_DATA_ROOT", tmp_path)
    monkeypatch.setenv("LATTICE_TOKEN", "env-token")
    assert server._auth_token() == "env-token"
    assert not (tmp_path / "auth_token.json").exists()
