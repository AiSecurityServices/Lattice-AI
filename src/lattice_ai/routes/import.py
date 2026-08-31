"""Unified import wizard backend: inspect/confirm with Dify-style four states.

``POST /api/import/inspect`` sniffs the pasted content, produces a Tool draft
and classifies the outcome:

- ``completed``: fully parsed, nothing to fill;
- ``completed_with_warnings``: parsed but e.g. the output schema is empty;
- ``pending``: required info missing (a literal API key in the command, an MCP
  server command that cannot be resolved) — the draft is stashed in memory for
  10 minutes and completed via ``POST /api/import/confirm``;
- ``failed``: nothing could be parsed; ``reason`` says why.

Credential red line: every response masks secret-looking values (Flowise's
stripProtectedFields); the detection regex is shared with approval.py.
"""

import threading
import time
import uuid

from fastapi import APIRouter, HTTPException

from lattice_ai import runtime as rt
from lattice_ai.models import Tool, from_dict, to_dict
from lattice_ai.tool_import import (
    env_name as _env_name,
    flag_name as _flag_name,
    list_mcp_tools,
    mcp_tools_to_lattice,
    parse_command,
    placeholder_name as _placeholder_name,
    script_tool_from_source,
    sniff_source,
)

router = APIRouter()

DRAFT_TTL_SECONDS = 600  # pending drafts expire after 10 minutes; re-inspect then
_MASK = "[REDACTED]"

_pending_drafts: dict[str, dict] = {}
_drafts_lock = threading.Lock()


def _mask_command(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Mask literal credential values in an argv. Returns (masked argv, names
    of credentials that must be filled before the tool can run). Placeholders
    like ``{api_key}`` are fine as-is — they are filled at run time."""
    out: list[str] = []
    missing: list[str] = []
    i = 0
    tokens = list(tokens or [])
    while i < len(tokens):
        tok = tokens[i]
        flag = _flag_name(tok)
        env = _env_name(tok)
        if flag is None and env is None:
            out.append(tok)
            i += 1
            continue
        name = flag or env
        if env is not None:
            out.append(tok.split("=", 1)[0] + "=" + _MASK)
            missing.append(name)
            i += 1
            continue
        if "=" in tok:
            out.append(tok.split("=", 1)[0] + "=" + _MASK)
            missing.append(name)
            i += 1
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        out.append(tok)
        if nxt is None:
            missing.append(name)
        elif _placeholder_name(nxt) or _flag_name(nxt):
            out.append(nxt)
            i += 1
        else:
            out.append(_MASK)
            missing.append(name)
            i += 1
        i += 1
    return out, missing


def _literal_secret_values(tokens: list[str]) -> list[str]:
    """The literal values that sit in credential slots of the argv."""
    values: list[str] = []
    i = 0
    tokens = list(tokens or [])
    while i < len(tokens):
        tok = tokens[i]
        name = _flag_name(tok) or _env_name(tok)
        if name is None:
            i += 1
            continue
        if "=" in tok:
            values.append(tok.split("=", 1)[1])
            i += 1
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None and not _placeholder_name(nxt) and not _flag_name(nxt):
            values.append(nxt)
            i += 1
        i += 1
    return values


def _mask_tool(draft: dict) -> dict:
    masked = dict(draft or {})
    command = [str(t) for t in (masked.get("command") or [])]
    masked["command"], _ = _mask_command(command)
    secrets = _literal_secret_values(command)
    if secrets:
        def scrub(value: str) -> str:
            for secret in secrets:
                value = value.replace(secret, _MASK)
            return value

        # The draft description echoes the pasted command; scrub every string
        # field so a literal key never leaves the process in any shape.
        for key, value in list(masked.items()):
            if isinstance(value, str):
                masked[key] = scrub(value)
    return masked


def _tool_warnings(draft: dict) -> list[str]:
    warnings = []
    output = draft.get("output") or {}
    if not isinstance(output, dict) or not output.get("properties"):
        warnings.append("output schema 为空：建议在试运行步粘贴一段真实输出生成提取规则")
    if not (draft.get("description") or "").strip():
        warnings.append("缺少工具描述")
    if draft.get("runner") == "cli" and draft.get("command"):
        if rt.find_executable(str(draft["command"][0])) is None:
            warnings.append(f"可执行文件 {draft['command'][0]} 未安装，试运行前请先安装")
    return warnings


def _missing_fields(draft: dict) -> dict:
    approvals = {draft.get("name", "")} if draft.get("approval") in ("ask", "deny") else set()
    return {
        "secrets": [],
        "tools": [],
        "approvals": sorted(name for name in approvals if name),
    }


def _literal_secret_slots(command: list[str]) -> tuple[list[str], dict[str, int]]:
    """Names of credentials that appear as literal values in the argv, with the
    token index each value sits at (the slot confirm() overwrites)."""
    missing: list[str] = []
    slots: dict[str, int] = {}
    i = 0
    tokens = list(command or [])
    while i < len(tokens):
        tok = tokens[i]
        name = _flag_name(tok) or _env_name(tok)
        if name is None:
            i += 1
            continue
        if "=" in tok:
            slots.setdefault(name, i)
            missing.append(name)
            i += 1
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is None:
            slots.setdefault(name, i + 1)
            missing.append(name)
        elif _placeholder_name(nxt) or _flag_name(nxt):
            i += 1
            continue
        else:
            slots.setdefault(name, i + 1)
            missing.append(name)
            i += 1
        i += 1
    return missing, slots


def _draft_from_content(content: str, kind: str) -> tuple[dict, list[str]]:
    """Produce a raw Tool draft dict for the sniffed kind; raises ValueError
    with a user-facing reason when nothing can be parsed."""
    if kind == "mcp":
        value = content.strip()
        if value.startswith("mcp://"):
            value = value[len("mcp://"):].strip()
        command = parse_command(value)
        tools = list_mcp_tools(command)
        drafts = [to_dict(t) for t in mcp_tools_to_lattice(tools, command=command)]
        warnings = []
        if len(drafts) > 1:
            warnings.append(f"MCP server 暴露 {len(drafts)} 个工具，已取第一个，其余请逐个导入")
        return drafts[0], warnings
    if kind == "command":
        return to_dict(script_tool_from_source(content)), []
    # paste / url / github need the LLM
    provider = rt._get_provider()
    if provider is None:
        raise ValueError("LLM 未配置：请先在设置里填写 API Key，或直接粘贴可执行的命令行")
    from lattice_ai.importer import generate_tool_draft

    return to_dict(from_dict(Tool, generate_tool_draft(provider, content))), []


def _inspect(content: str, kind_hint: str = "") -> dict:
    content = str(content or "")
    if not content.strip():
        return {"status": "failed", "reason": "导入内容为空", "draft": None,
                "missing": {"secrets": [], "tools": [], "approvals": []}, "warnings": []}
    # ``source`` is an optional type hint, not a channel selector: a "paste"
    # hint still runs the sniffer first — command/MCP content keeps its
    # deterministic path, only prose falls through to the LLM.
    kind = kind_hint if kind_hint in ("paste", "url", "mcp", "github") else ""
    if kind == "paste":
        sniffed = sniff_source(content)
        if sniffed in ("command", "mcp"):
            kind = sniffed
    kind = kind or sniff_source(content)
    warnings: list[str] = []
    try:
        if kind == "mcp" and not parse_command(
            content.strip()[len("mcp://"):] if content.strip().startswith("mcp://") else content.strip()
        ):
            return {
                "status": "pending",
                "draft_id": _stash({"name": "mcp-tool", "runner": "adapter", "adapter": "mcp", "command": []}, {}),
                "draft": None,
                "missing": {"secrets": [], "tools": ["mcp-server"], "approvals": []},
                "warnings": ["MCP 缺少 server 启动命令，请补齐后再确认"],
            }
        draft, extra_warnings = _draft_from_content(content, kind)
        warnings.extend(extra_warnings)
    except Exception as exc:
        return {"status": "failed", "reason": str(exc) or "无法解析导入内容", "draft": None,
                "missing": {"secrets": [], "tools": [], "approvals": []}, "warnings": []}

    command = [str(t) for t in (draft.get("command") or [])]
    literal_missing, slots = _literal_secret_slots(command)
    missing = _missing_fields(draft)
    missing["secrets"] = sorted(set(literal_missing))
    if draft.get("runner") == "cli" and command and rt.find_executable(command[0]) is None:
        missing["tools"] = [command[0]]
    warnings.extend(_tool_warnings(draft))
    status = "pending" if missing["secrets"] else (
        "completed_with_warnings" if warnings else "completed"
    )
    draft_id = _stash(draft, slots) if status == "pending" else None
    return {
        "status": status,
        "draft_id": draft_id,
        "draft": _mask_tool(draft),
        "missing": missing,
        "warnings": warnings,
    }


@router.post("/api/import/output-schema")
def output_schema_from_sample(body: dict):
    """Wizard step 4 helper: paste one real output sample, get a Tool.output
    JSON Schema the LLM derived from it."""
    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM 未配置")
    tool = body.get("tool") or {}
    sample = str(body.get("sample") or "")
    if not sample.strip():
        raise HTTPException(status_code=400, detail="sample is required")
    from lattice_ai.importer import generate_output_schema

    try:
        schema = generate_output_schema(provider, tool, sample)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to derive output schema: {exc}") from exc
    return {"output": schema}


def _stash(draft: dict, slots: dict[str, int]) -> str:
    draft_id = uuid.uuid4().hex
    with _drafts_lock:
        now = time.monotonic()
        for key in [k for k, v in _pending_drafts.items() if now - v["created"] > DRAFT_TTL_SECONDS]:
            _pending_drafts.pop(key, None)
        _pending_drafts[draft_id] = {
            "draft": draft,
            "slots": slots or {},
            "created": now,
        }
    return draft_id


def _pop_stash(draft_id: str) -> dict:
    with _drafts_lock:
        record = _pending_drafts.pop(draft_id, None)
    if record is None:
        raise HTTPException(status_code=404, detail="draft not found")
    if time.monotonic() - record["created"] > DRAFT_TTL_SECONDS:
        raise HTTPException(status_code=410, detail="draft 已过期（10 分钟），请重新 inspect")
    return record


@router.post("/api/import/inspect")
def inspect_import(body: dict):
    return _inspect(body.get("content", ""), str(body.get("source") or ""))


@router.post("/api/import/confirm")
def confirm_import(body: dict):
    fills = body.get("fills") or {}
    draft_id = str(body.get("draft_id") or "")
    draft = body.get("draft")
    if draft_id:
        record = _pop_stash(draft_id)
        draft = record["draft"]
        slots = record.get("slots") or {}
        command = [str(t) for t in (draft.get("command") or [])]
        for name, value in (fills.get("secrets") or {}).items():
            idx = slots.get(name)
            if idx is None or idx >= len(command):
                continue
            command[idx] = str(value)
        draft["command"] = command
    if not draft:
        raise HTTPException(status_code=400, detail="draft is required")
    for key in ("name", "category", "description"):
        if fills.get(key):
            draft[key] = str(fills[key])
    try:
        tool = from_dict(Tool, draft)
        tool.name = tool.name.strip()
        if not tool.name:
            raise ValueError("工具名称不能为空")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid tool draft: {exc}") from exc
    rt._tool_store.save(tool.name, to_dict(tool))
    return {"name": tool.name, "tool": _mask_tool(to_dict(tool))}
