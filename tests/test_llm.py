import json
import io
import urllib.error

import pytest

from lattice_ai.llm import OpenAICompatibleProvider, _map_effort, build_request, list_models, parse_response


def test_build_request_converts_tool_calls():
    messages = [
        {"role": "system", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"msg": "x"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"value": "x"}'},
    ]
    tools = [{"type": "function", "function": {"name": "echo", "parameters": {}}}]
    payload = build_request("gpt-x", messages, tools)
    assert payload["model"] == "gpt-x"
    assert payload["tools"] == tools
    assert payload["messages"][1]["tool_calls"][0]["function"]["arguments"] == '{"msg": "x"}'
    assert payload["messages"][2]["tool_call_id"] == "c1"


def test_parse_response_normalizes_tool_calls():
    data = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "echo", "arguments": '{"msg": "hi"}'}}
                    ],
                }
            }
        ]
    }
    result = parse_response(data)
    assert result["content"] is None
    assert result["tool_calls"] == [{"id": "c1", "name": "echo", "arguments": {"msg": "hi"}}]


def test_provider_falls_back_to_chat_completions(monkeypatch):
    class Resp:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/models"):
            raise urllib.error.URLError("no /models endpoint")
        return Resp(200)

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider("https://example.com/v1", "sk", "m")
    assert provider.test() is True


def test_build_request_injects_reasoning_effort():
    payload = build_request("m", [{"role": "user", "content": "hi"}], [], reasoning_effort="medium")
    assert payload["reasoning_effort"] == "medium"


def test_build_request_injects_thinking_for_deepseek():
    payload = build_request("m", [{"role": "user", "content": "hi"}], [], thinking={"type": "disabled"})
    assert payload["thinking"] == {"type": "disabled"}


def test_map_effort_off_disables_thinking_for_deepseek():
    assert _map_effort("off", is_deepseek=True) == (None, {"type": "disabled"})
    assert _map_effort("off") == ("none", None)


def test_map_effort_ui_values():
    # off/low/medium/high
    assert _map_effort("low") == ("low", None)
    assert _map_effort("medium") == ("medium", None)
    assert _map_effort("high") == ("high", None)
    assert _map_effort("max") == ("max", None)


def test_list_models_parses_ids_and_reasoning(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data":[{"id":"deepseek-v4-pro","owned_by":"deepseek"},{"id":"deepseek-v4-flash","reasoning_effort":"high"}]}'

    def fake_urlopen(req, timeout=None):
        return Resp()

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", fake_urlopen)
    models = list_models("https://api.deepseek.com", "sk")
    assert [m["id"] for m in models] == ["deepseek-v4-pro", "deepseek-v4-flash"]
    assert models[1]["reasoning_efforts"] == ["high"]


def test_stream_chat_yields_deltas_and_assembles_tool_calls(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            lines = [
                b'data: {"choices":[{"delta":{"content":"He"}}]}\n\n',
                b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"echo","arguments":"{\\"msg\\":\\"x\\"}"}}]}}]}\n\n',
                b'data: [DONE]\n\n',
            ]
            return iter(lines)

    def fake_urlopen(req, timeout=None):
        assert json.loads(req.data.decode("utf-8"))["stream"] is True
        return Resp()

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider("https://api.openai.com/v1", "sk", "m")
    events = list(provider.stream_chat([{"role": "user", "content": "hi"}], []))
    deltas = [e["content"] for e in events if e["type"] == "delta"]
    assert "".join(deltas) == "Hello"
    done = events[-1]
    assert done["type"] == "done"
    assert done["tool_calls"] == [{"id": "c1", "name": "echo", "arguments": {"msg": "x"}}]


def test_chat_retries_without_reasoning_effort_on_400(monkeypatch):
    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, timeout=None):
        calls.append(json.loads(req.data.decode("utf-8")))
        if len(calls) == 1:
            raise urllib.error.HTTPError("x", 400, "Bad Request", {}, None)
        return Resp()

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider("https://api.deepseek.com/v1", "sk", "deepseek-v4-pro", reasoning_effort="max")
    result = provider.chat([{"role": "user", "content": "hi"}], [])
    assert result["content"] == "ok"
    assert "reasoning_effort" in calls[0]
    assert "reasoning_effort" not in calls[1]
    assert "thinking" not in calls[1]


def test_chat_surfaces_400_body(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError("x", 400, "Bad Request", {}, io.BytesIO(b'{"error":{"message":"invalid model name"}}'))

    monkeypatch.setattr("lattice_ai.llm.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider("https://api.deepseek.com/v1", "sk", "deepseek-v4-pro", reasoning_effort="max")
    with pytest.raises(ValueError) as exc_info:
        provider.chat([{"role": "user", "content": "hi"}], [])
    assert "invalid model name" in str(exc_info.value)
