import json
import sys

import lattice_ai.adapters  # noqa: F401  # registers mcp/http_api adapters
from lattice_ai.models import Tool
from lattice_ai.tools import get_adapter


MCP_SERVER = r'''
import json, sys
for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    i = msg.get("id")
    method = msg.get("method", "")
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}}), flush=True)
    elif method == "notifications/initialized":
        pass
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        print(json.dumps({"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": f"{name}:{args.get('q', '')}"}]}}), flush=True)
'''


def test_mcp_adapter_invoke(tmp_path):
    script = tmp_path / "mcp_server.py"
    script.write_text(MCP_SERVER, encoding="utf-8")
    adapter = get_adapter("mcp")
    tool = Tool(
        name="greet",
        runner="adapter",
        adapter="mcp",
        ref="greet_tool",
        command=[sys.executable, str(script)],
        parameters={"type": "object", "properties": {"q": {"type": "string"}}},
    )
    result = adapter.invoke(tool, {"q": "hi"}, timeout=10)
    assert "greet_tool:hi" in result["text"]


def test_http_api_adapter_invoke(monkeypatch):
    adapter = get_adapter("http_api")
    tool = Tool(
        name="lookup",
        runner="adapter",
        adapter="http_api",
        ref="/items/{id}",
        command=["GET", "http://127.0.0.1:9"],
    )
    captured = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return FakeResp()

    monkeypatch.setattr("lattice_ai.adapters.http_api.urllib.request.urlopen", fake_urlopen)
    result = adapter.invoke(tool, {"id": 42}, timeout=5)
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/items/42")
    assert result == {"ok": True}


def test_http_api_adapter_post_json(monkeypatch):
    adapter = get_adapter("http_api")
    tool = Tool(
        name="create",
        runner="adapter",
        adapter="http_api",
        ref="",
        command=["POST", "http://127.0.0.1:9/items"],
    )
    captured = {}

    class FakeResp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"id": 2}).encode()

    def fake_urlopen(req, timeout=None):
        captured["method"] = req.get_method()
        captured["data"] = req.data
        return FakeResp()

    monkeypatch.setattr("lattice_ai.adapters.http_api.urllib.request.urlopen", fake_urlopen)
    result = adapter.invoke(tool, {"name": "x"}, timeout=5)
    assert captured["method"] == "POST"
    assert json.loads(captured["data"]) == {"name": "x"}
    assert result == {"id": 2}
