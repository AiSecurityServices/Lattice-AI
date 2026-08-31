import json
import random
import time
import urllib.error
import urllib.request
from typing import Protocol

# Transient upstream failures worth a retry before surfacing an error.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class Provider(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return {'content': str|None, 'tool_calls': [{'id','name','arguments':dict}]}."""
        ...


def _to_openai_message(msg: dict) -> dict:
    role = msg["role"]
    if role == "tool":
        return {"role": "tool", "tool_call_id": msg["tool_call_id"], "content": msg.get("content")}
    if role == "assistant" and msg.get("tool_calls"):
        tool_calls = [
            {
                "id": t["id"],
                "type": "function",
                "function": {"name": t["name"], "arguments": json.dumps(t.get("arguments") or {})},
            }
            for t in msg["tool_calls"]
        ]
        return {"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls}
    return {"role": role, "content": msg.get("content")}


def _map_effort(value, is_deepseek=False):
    """Map UI off/low/medium/high to OpenAI-compatible request params.

    Returns (reasoning_effort, thinking). DeepSeek 关闭思考走 thinking 开关，
    OpenAI 关闭思考走 reasoning_effort=none。DeepSeek 会把 medium 映射为 high。
    """
    if value == "off":
        if is_deepseek:
            return None, {"type": "disabled"}
        return "none", None
    if value == "max":
        return "max", None
    return value, None


def list_models(base_url: str, api_key: str, timeout: float = 15.0) -> list[dict]:
    """Fetch the provider's OpenAI-compatible /models list using the given API key.

    Returns a list of {id, reasoning_efforts?, supports_reasoning?} dicts. Plain
    OpenAI / DeepSeek endpoints return only ids; OpenRouter-style endpoints that
    embed reasoning metadata preserve it.
    """
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    raw = data.get("data", data)
    if not isinstance(raw, list):
        raw = []
    models = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("name")
        if not mid:
            continue
        item = {"id": mid}
        reff = (
            m.get("reasoning_effort")
            or (m.get("reasoning") or {}).get("efforts")
            or (m.get("capabilities") or {}).get("reasoning_efforts")
            or (m.get("reasoning_efforts"))
        )
        if reff:
            item["reasoning_efforts"] = [e for e in (reff if isinstance(reff, list) else [reff]) if e]
        supports = (m.get("capabilities") or {}).get("supportsReasoning")
        if supports is not None:
            item["supports_reasoning"] = bool(supports)
        models.append(item)
    return models


def build_request(model: str, messages: list[dict], tools: list[dict], reasoning_effort=None, thinking=None) -> dict:
    payload = {"model": model, "messages": [_to_openai_message(m) for m in messages]}
    if tools:
        payload["tools"] = tools
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if thinking:
        payload["thinking"] = thinking
    return payload


def _normalize_usage(usage) -> dict | None:
    """Fold a gateway's usage object into {prompt_tokens, completion_tokens,
    total_tokens}; None when the gateway did not report any usage."""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    if prompt is None and completion is None and total is None:
        return None
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def parse_response(data: dict) -> dict:
    choice = data["choices"][0]["message"]
    content = choice.get("content")
    raw = choice.get("tool_calls") or []
    tool_calls = []
    for tc in raw:
        fn = tc.get("function") or {}
        try:
            arguments = json.loads(fn.get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        tool_calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": arguments})
    return {"content": content, "tool_calls": tool_calls, "usage": _normalize_usage(data.get("usage"))}


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0, reasoning_effort=None):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "")
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        is_deepseek = "deepseek" in self.base_url
        eff, thinking = _map_effort(self.reasoning_effort, is_deepseek=is_deepseek)
        payload = build_request(self.model, messages, tools, reasoning_effort=eff, thinking=thinking)
        url = self.base_url + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        with self._post(url, headers, payload) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return parse_response(data)

    def _post(self, url, headers, payload):
        def send_once(body):
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            return urllib.request.urlopen(req, timeout=self.timeout)

        def send(body):
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    return send_once(body)
                except urllib.error.HTTPError as exc:
                    if exc.code not in _RETRYABLE_STATUS or attempt == _MAX_ATTEMPTS - 1:
                        raise
                except (urllib.error.URLError, TimeoutError, OSError):
                    if attempt == _MAX_ATTEMPTS - 1:
                        raise
                time.sleep(0.5 * (2 ** attempt) + random.random() * 0.2)
            raise RuntimeError("unreachable")

        def _body(exc):
            try:
                return exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                return ""

        try:
            return send(payload)
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                stripped = {k: v for k, v in payload.items() if k not in ("reasoning_effort", "thinking")}
                try:
                    return send(stripped)
                except urllib.error.HTTPError as exc2:
                    raise ValueError(f"LLM request failed ({exc2.code}): {_body(exc2) or exc2}") from exc2
            raise ValueError(f"LLM request failed ({exc.code}): {_body(exc) or exc}") from exc

    def stream_chat(self, messages: list[dict], tools: list[dict]):
        """Yield event dicts streaming an OpenAI-compatible chat completion.

        Yields {"type": "delta", "content": str} as text arrives, then a final
        {"type": "done", "content": str, "tool_calls": [...]} when the stream ends.
        """
        is_deepseek = "deepseek" in self.base_url
        eff, thinking = _map_effort(self.reasoning_effort, is_deepseek=is_deepseek)
        payload = build_request(self.model, messages, tools, reasoning_effort=eff, thinking=thinking)
        payload["stream"] = True
        url = self.base_url + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        with self._post(url, headers, payload) as resp:
            content_parts = []
            tool_calls = {}
            usage = None
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                raw_data = line[5:].strip()
                if raw_data == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choice = (chunk.get("choices") or [None])[0] or {}
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if content:
                    content_parts.append(content)
                    yield {"type": "delta", "content": content}
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    entry = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["name"] = fn["name"]
                    if fn.get("arguments"):
                        entry["arguments"] += fn["arguments"]
            tool_call_list = []
            for idx in sorted(tool_calls):
                entry = tool_calls[idx]
                try:
                    args = json.loads(entry["arguments"]) if entry["arguments"].strip() else {}
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_call_list.append({"id": entry["id"], "name": entry["name"], "arguments": args})
        yield {
            "type": "done",
            "content": "".join(content_parts),
            "tool_calls": tool_call_list,
            "usage": _normalize_usage(usage),
        }

    def test(self) -> bool:
        return self._test_models() or self._test_chat_completions()

    def _test_models(self) -> bool:
        url = self.base_url + "/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _test_chat_completions(self) -> bool:
        url = self.base_url + "/chat/completions"
        payload = {"model": self.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
                return resp.status == 200
        except Exception:
            return False
