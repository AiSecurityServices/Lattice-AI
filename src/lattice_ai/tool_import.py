import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from lattice_ai.approval import _SENSITIVE_KEY
from lattice_ai.importer import generate_tool_draft
from lattice_ai.models import Tool, from_dict

_MCP_PREFIXES = {"npx", "uvx", "bunx", "pnpm", "python", "python3", "python.exe"}


def parse_command(source: str) -> list[str]:
    parts = shlex.split(source, posix=(os.name != "nt"))
    if os.name != "nt":
        return parts
    cleaned = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in ("\"", "'"):
            cleaned.append(part[1:-1])
        else:
            cleaned.append(part)
    return cleaned


def detect_mcp(source: str, provider=None) -> bool:
    value = (source or "").strip()
    if not value:
        return False
    if value.startswith("mcp://"):
        return True
    tokens = value.split()
    if tokens and tokens[0].lower() in _MCP_PREFIXES:
        return True
    if "mcp" in value.lower():
        return True
    if provider is None:
        return False
    prompt = (
        "Does this text describe an MCP server startup command? "
        "Answer only YES or NO.\n\n" + value
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    return "yes" in (response.get("content") or "").strip().lower()


def _send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _recv(proc, want_id):
    for _ in range(120):
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("id") == want_id:
            return msg
    return None


def list_mcp_tools(command: list[str], *, cwd=None, timeout: float = 15.0) -> list[dict]:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    try:
        _send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "lattice", "version": "0.1.0"},
            },
        })
        _recv(proc, 1)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        result = _recv(proc, 2)
        if not result or "error" in result:
            raise ValueError(f"tools/list failed: {result}")
        return result.get("result", {}).get("tools", [])
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()


def mcp_tool_to_lattice(raw: dict, *, command: list[str]) -> Tool:
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("mcp tool has no name")
    schema = raw.get("inputSchema")
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return Tool(
        name=name,
        description=raw.get("description", ""),
        parameters=schema,
        output={},
        runner="adapter",
        adapter="mcp",
        ref=name,
        command=list(command),
        scope=[],
        approval="ask",
        secret_fields=[],
    )


def mcp_tools_to_lattice(raw_tools: list[dict], *, command: list[str]) -> list[Tool]:
    return [mcp_tool_to_lattice(raw, command=command) for raw in raw_tools]


def classify_source(source: str) -> str:
    """Classify a free-text import source into its family."""
    value = (source or "").strip()
    if not value:
        return "description"
    if value.startswith("mcp://"):
        return "mcp"
    if value.startswith(("http://", "https://")):
        if "github.com" in value or "raw.githubusercontent.com" in value:
            return "github"
        return "url"
    if os.path.exists(value):
        return "script"
    tokens = value.split()
    if tokens and tokens[0].lower() in _MCP_PREFIXES:
        return "mcp"
    if "mcp" in value.lower():
        return "mcp"
    if "/" in value or "\\" in value:
        return "script"
    return "description"


def looks_like_command(source: str) -> bool:
    """True when the text reads as a shell command (executable + flags or
    {placeholder} args) rather than a natural-language description."""
    value = (source or "").strip()
    if not value or "\n" in value.strip():
        return False
    tokens = value.split()
    if not tokens:
        return False
    if any(ch in tokens[0] for ch in "\"'`"):
        return False
    rest = tokens[1:]
    if not rest:
        return False
    return any(
        part.startswith("-") or (part.startswith("{") and part.endswith("}"))
        for part in rest
    )


def sniff_source(source: str) -> str:
    """Decide which import path a pasted blob should take:
    mcp | url | github | command | paste (description for the LLM)."""
    value = (source or "").strip()
    if not value:
        return "paste"
    if value.startswith("mcp://"):
        return "mcp"
    if value.startswith(("http://", "https://")):
        return "github" if ("github.com" in value or "raw.githubusercontent.com" in value) else "url"
    tokens = value.split()
    if tokens and tokens[0].lower() in _MCP_PREFIXES:
        return "mcp"
    if looks_like_command(value):
        return "command"
    if "mcp" in value.lower():
        return "mcp"
    if os.path.exists(value):
        return "command"
    return "paste"


def script_tool_from_source(source: str) -> Tool:
    """Build a CLI Tool from a local file path or command string."""
    value = (source or "").strip()
    path = Path(value)
    if path.exists() and path.is_file():
        name = path.stem
        if path.suffix.lower() == ".py":
            command = [sys.executable, str(path)]
        elif path.suffix.lower() in (".sh", ".bash"):
            command = ["bash", str(path)]
        else:
            command = [str(path)]
    else:
        command = parse_command(value)
        if not command:
            raise ValueError("empty script command")
        name = Path(command[0]).stem or command[0]
    return Tool(
        name=name,
        description=f"Imported script: {value}",
        parameters={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
        output={},
        runner="cli",
        command=command,
        scope=[],
        approval="ask",
        secret_fields=[],
    )


def github_tool_from_source(provider, source: str) -> Tool:
    """Build a Tool draft from a GitHub URL or natural-language description."""
    draft = generate_tool_draft(provider, source)
    return from_dict(Tool, draft)


def import_tool_source(provider, source: str) -> list[Tool]:
    """Route a free-text source to zero or more normalized Tools."""
    kind = classify_source(source)
    if kind == "mcp":
        value = source.strip()
        if value.startswith("mcp://"):
            value = value[len("mcp://"):].strip()
        command = parse_command(value)
        return mcp_tools_to_lattice(list_mcp_tools(command), command=command)
    if kind == "script":
        return [script_tool_from_source(source)]
    if kind in ("github", "url", "description"):
        return [github_tool_from_source(provider, source)]
    return []


def map_target_to_args(provider, tool: Tool, target: str) -> dict:
    prompt = (
        "Map the target to the tool's JSON Schema arguments. "
        "Always include the target in the most appropriate field. "
        "Return ONLY a JSON object.\n\n"
        f"Target: {target}\n"
        f"Tool: {tool.name}\n"
        f"Parameters: {json.dumps(tool.parameters, ensure_ascii=False)}\n"
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    text = (response.get("content") or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("provider did not return a JSON object")
    return json.loads(text[start : end + 1])


def flag_name(token: str) -> str | None:
    """Credential flag name when the token is ``--api-key`` / ``--api-key=...``.
    Hyphens are folded to underscores so ``api-key`` matches ``api_?key``."""
    t = (token or "").strip()
    if not t.startswith("--"):
        return None
    name = t[2:].split("=", 1)[0].replace("-", "_")
    return name if _SENSITIVE_KEY.search(name) else None


def env_name(token: str) -> str | None:
    """Credential key when the token is ``API_KEY=...`` (no dashes)."""
    t = (token or "").strip()
    if t.startswith("-") or "=" not in t:
        return None
    key = t.split("=", 1)[0]
    return key if _SENSITIVE_KEY.search(key) else None


def placeholder_name(token: str) -> str | None:
    t = (token or "").strip()
    if t.startswith("{") and t.endswith("}") and _SENSITIVE_KEY.search(t[1:-1].replace("-", "_")):
        return t[1:-1]
    return None


def secret_names_in_command(tokens) -> list[str]:
    """Every credential name referenced by an argv (flags, env keys, placeholders)."""
    names = []
    for tok in tokens or []:
        for check in (flag_name, env_name, placeholder_name):
            name = check(str(tok))
            if name:
                names.append(name)
                break
    return names


def template_dependencies(template: dict) -> dict:
    """Pre-install dependency sheet for a marketplace template: which secrets,
    executables and approval decisions the template's tools will need."""
    secrets: set[str] = set()
    runners: set[str] = set()
    approvals: set[str] = set()
    for tool in template.get("tools", []) or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        if tool.get("approval") in ("ask", "deny") and name:
            approvals.add(name)
        for sf in tool.get("secret_fields") or []:
            secrets.add(str(sf).rsplit(".", 1)[-1])
        secrets.update(secret_names_in_command(tool.get("command") or []))
        command = [str(t) for t in (tool.get("command") or [])]
        if tool.get("runner") == "cli" and command:
            runners.add(command[0])
        elif tool.get("runner") == "adapter":
            runners.add(f"adapter:{tool.get('adapter') or 'mcp'}")
    return {"secrets": sorted(secrets), "runners": sorted(runners), "approvals": sorted(approvals)}
