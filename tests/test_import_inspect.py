import json
import time

import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.tool_import import sniff_source
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


def _inspect(content, source=""):
    response = client.post("/api/import/inspect", json={"source": source, "content": content})
    assert response.status_code == 200
    return response.json()


class _FakeProvider:
    def __init__(self, content):
        self.content = content

    def chat(self, messages, tools=None):
        return {"content": self.content, "tool_calls": []}


def test_sniff_source_routes_families():
    assert sniff_source("nmap -sV -oX - {target}") == "command"
    assert sniff_source("nmap -sV {target}\nsecond line") == "paste"
    assert sniff_source("mcp://npx -y some-mcp") == "mcp"
    assert sniff_source("npx -y some-mcp") == "mcp"
    assert sniff_source("https://github.com/a/b/blob/main/x.py") == "github"
    assert sniff_source("https://example.com/tool.md") == "url"
    assert sniff_source("一个用于扫描子域名的自然语言描述") == "paste"


def test_inspect_completed_for_full_llm_draft(monkeypatch):
    draft = json.dumps({
        "name": "demo_scan",
        "description": "Demo scanner with a declared output",
        "runner": "builtin",
        "command": [],
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}},
        "output": {"type": "object", "properties": {"result": {"type": "string"}}},
    })
    monkeypatch.setattr(rt, "_get_provider", lambda: _FakeProvider(draft))
    result = _inspect("一个把目标端口扫出来的工具，输出 result 字段")
    assert result["status"] == "completed"
    assert result["draft"]["name"] == "demo_scan"
    assert result["draft"]["output"]["properties"]["result"]["type"] == "string"
    assert result["missing"]["secrets"] == []
    assert result["warnings"] == []


def test_inspect_completed_with_warnings_when_output_schema_empty():
    result = _inspect("httpx -u {target}")
    assert result["status"] == "completed_with_warnings"
    assert result["draft"]["runner"] == "cli"
    assert any("output schema" in w for w in result["warnings"])


def test_inspect_pending_when_command_carries_literal_api_key():
    result = _inspect("mytool --api-key sk-live-abcdef123456 {target}")
    assert result["status"] == "pending"
    assert result["draft_id"]
    assert result["missing"]["secrets"] == ["api_key"]
    body = json.dumps(result, ensure_ascii=False)
    assert "sk-live-abcdef123456" not in body  # credential red line: masked everywhere
    assert "[REDACTED]" in result["draft"]["command"]
    assert "{target}" in result["draft"]["command"]


def test_inspect_pending_for_env_style_and_placeholder_is_not_pending():
    result = _inspect("mytool API_KEY=sk-env-abcdef123456 {target}")
    assert result["status"] == "pending"
    assert result["missing"]["secrets"] == ["API_KEY"]
    assert "sk-env-abcdef123456" not in json.dumps(result)

    ok = _inspect("mytool --token {token} {target}")
    assert ok["status"] == "completed_with_warnings"  # placeholder fills at run time
    assert ok["missing"]["secrets"] == []


def test_inspect_failed_for_garbage():
    result = _inspect("!!! ??? ### 未成句的乱码")
    assert result["status"] == "failed"
    assert result["reason"]
    assert result["draft"] is None


def test_inspect_failed_for_empty_content():
    assert _inspect("   ")["status"] == "failed"


def test_inspect_pending_when_mcp_server_command_missing():
    result = _inspect("mcp://", source="mcp")
    assert result["status"] == "pending"
    assert "mcp-server" in result["missing"]["tools"]


def test_confirm_fills_secrets_and_stores_tool():
    inspect = _inspect("mytool --api-key sk-live-abcdef123456 {target}")
    response = client.post("/api/import/confirm", json={
        "draft_id": inspect["draft_id"],
        "fills": {"secrets": {"api_key": "sk-real-9876543210"}, "name": "mytool", "category": "vuln"},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "mytool"
    assert "sk-real-9876543210" not in json.dumps(body)  # response stays masked

    stored = rt._tool_store.get("mytool")
    assert stored is not None
    assert "sk-real-9876543210" in stored["command"]
    assert "{target}" in stored["command"]
    assert stored["category"] == "vuln"


def test_confirm_unknown_and_expired_drafts(monkeypatch):
    assert client.post("/api/import/confirm", json={"draft_id": "nope"}).status_code == 404

    inspect = _inspect("mytool --api-key sk-live-abcdef123456 {target}")
    from importlib import import_module

    import_module = import_module("lattice_ai.routes.import")
    # -1 (not 0): monotonic can return the same reading twice, so 0 is an
    # edge case that may not trip the expiry comparison.
    monkeypatch.setattr(import_module, "DRAFT_TTL_SECONDS", -1)
    response = client.post("/api/import/confirm", json={"draft_id": inspect["draft_id"]})
    assert response.status_code == 410


def test_marketplace_lists_dependencies(monkeypatch):
    template = {
        "id": "tpl",
        "name": "n",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "nuclei"}]}],
        "tools": [{
            "name": "nuclei",
            "runner": "cli",
            "command": ["nuclei", "-secret", "{token}"],
            "approval": "ask",
            "secret_fields": ["report.api_key"],
        }],
    }
    monkeypatch.setattr(rt, "_MARKETPLACE", {
        "tpl": {"id": "tpl", "name": "n", "description": "d", "requires_tools": [], "template": template},
    })
    items = client.get("/api/marketplace").json()["templates"]
    deps = items[0]["dependencies"]
    assert deps["secrets"] == ["api_key", "token"]
    assert deps["runners"] == ["nuclei"]
    assert deps["approvals"] == ["nuclei"]


def test_import_wizard_end_to_end_paste_to_bindable_tool(monkeypatch):
    """Acceptance: paste `nmap -sV -oX - {target}` → tool card → trial run →
    stored → bindable to a template, no backend errors along the way."""
    monkeypatch.setattr(rt, "_get_provider", lambda: _FakeProvider('{"target": "scanme.example.com"}'))

    # 1) paste → inspect produces a tool card (schemas visible, warnings only)
    inspect = _inspect("nmap -sV -oX - {target}")
    assert inspect["status"] == "completed_with_warnings"
    draft = inspect["draft"]
    assert draft["runner"] == "cli"
    assert "{target}" in draft["command"]
    assert draft["parameters"]["properties"]["target"]["type"] == "string"

    # 2) trial run via try + try/execute (builtin nmap fallback when absent)
    trial = client.post("/api/tools/try", json={"tool": draft, "target": "scanme.example.com"})
    assert trial.status_code == 200
    approval_id = trial.json()["approval_id"]
    resolved = client.post(f"/api/approvals/{approval_id}/resolve", json={"approved": True})
    assert resolved.status_code == 200
    executed = client.post("/api/tools/try/execute", json={"approval_id": approval_id})
    assert executed.status_code == 200
    result = executed.json()["result"]
    assert isinstance(result, dict)
    assert "error" not in result  # builtin fallback produced a real result

    # 3) store the tool, then bind it to any template
    stored = client.post("/api/tools/imported", json={"tool": draft})
    assert stored.status_code == 200
    assert any(t["name"] == "nmap" for t in rt._tool_store.list())

    template = {
        "id": "bind-tpl",
        "name": "n",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": []}],
        "tools": [],
    }
    assert client.put("/api/templates/bind-tpl", json=template).status_code == 200
    bound = client.post("/api/tools/nmap/bind", json={"template_id": "bind-tpl", "stage_id": "a"})
    assert bound.status_code == 200
    tools = client.get("/api/templates/bind-tpl/tools").json()["tools"]
    assert any(t["name"] == "nmap" for t in tools)


def test_paste_hint_still_routes_shell_content_to_command_path(monkeypatch):
    """Contract: `source` is a type hint, not a channel selector. A caller that
    labels shell content as paste must not be forced into the LLM path."""
    def _boom(*args, **kwargs):  # LLM must not be needed
        raise AssertionError("LLM provider must not be used for shell commands")
    monkeypatch.setattr(rt, "_get_provider", _boom)

    result = _inspect("nmap -sV -oX - {target}", source="paste")
    assert result["status"] == "completed_with_warnings"
    assert result["draft"]["runner"] == "cli"
    assert "{target}" in result["draft"]["command"]

    # Multi-line prose under a paste hint stays on the LLM path (fails without
    # a provider, proving the hint is still honored for non-command content).
    prose = _inspect("一个用于扫描子域名的工具", source="paste")
    assert prose["status"] == "failed"
    assert "LLM" in prose["reason"]


def test_paste_hint_defers_to_sniffer_for_mcp(monkeypatch):
    """A paste hint must not force MCP content down the LLM path either."""
    from importlib import import_module

    import_module = import_module("lattice_ai.routes.import")
    monkeypatch.setattr(import_module, "list_mcp_tools", lambda cmd: [
        {"name": "sample-mcp", "description": "d", "inputSchema": {"type": "object", "properties": {}}}
    ])
    monkeypatch.setattr(rt, "_get_provider", lambda: (_ for _ in ()).throw(AssertionError("LLM must not be used")))

    result = _inspect("npx -y some-mcp-server", source="paste")
    assert result["status"] == "completed_with_warnings"
    assert result["draft"]["runner"] == "adapter"
    assert result["draft"]["name"] == "sample-mcp"
