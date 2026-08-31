"""Conversation / chat / assistant routes (extracted from server.py)."""
import asyncio
import hashlib
import json
import os
import queue
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from lattice_ai import adapters  # noqa: F401  # registers mcp/http_api tool adapters
from lattice_ai import runtime as rt
from lattice_ai.agent import StageAgent, WorkflowAgent
from lattice_ai.approval import create_pending as approval_create_pending, get_pending as approval_get_pending, resolve_pending as approval_resolve_pending
from lattice_ai.assistant import AssistantAgent
from lattice_ai.asset_extractor import extract_assets_from_facts
from lattice_ai.builtins import install_builtins
from lattice_ai.capability import capability_of
from lattice_ai.chat import ChatAgent
from lattice_ai.danger import add_whitelist, danger_policy_default, evaluate_danger, remove_whitelist
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.generation import generation_done, generation_exists, generation_result, list_generation_events, start_generation
from lattice_ai.graph import GraphError, validate_template
from lattice_ai.improve import apply_suggestion
from lattice_ai.groups import next_group_id
from lattice_ai.importer import generate_tool_draft
from lattice_ai.github_asset_importer import preview_asset_import
from lattice_ai.installer import go_bin_dir, install_toolchain
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.llm import OpenAICompatibleProvider, list_models
from lattice_ai.models import Skill, Tool, ToolBinding, Template, from_dict, to_dict
from lattice_ai.preferences import load_preferences, save_preferences
from lattice_ai.recipes import load_bundled_recipes, tool_to_yaml, yaml_to_tool
from lattice_ai.report_export import export_report
from lattice_ai.run_context import build_run_context
from lattice_ai.run_diff import diff_runs
from lattice_ai.run_replay import replay_page
from lattice_ai.run_state import load_run_state, next_ready, save_run_state
from lattice_ai.review import generate_findings, generate_report, generate_report_stream, review_workflow, understand_workflow
from lattice_ai.scope import evaluate_scope, is_restricted_target, scope_configured, scope_policy_from_dict
from lattice_ai.selfcheck import evolution_report, group_units, self_check_unit
from lattice_ai.tools import ApprovalDenied, ToolError, ToolRegistry, add_tool_path, find_executable, tool_available, tool_status
from lattice_ai.tool_import import classify_source, detect_mcp, import_tool_source, list_mcp_tools, map_target_to_args, mcp_tools_to_lattice, parse_command

router = APIRouter()




class ChatRequest(BaseModel):
    template: dict
    message: str
    history: list[dict] = []
    facts: dict = {}


class AssistantRequest(BaseModel):
    message: str
    history: list[dict] = []
    confirm: dict | None = None


class ConversationCreate(BaseModel):
    kind: str
    template_id: str = ""
    name: str = ""
    model: str = ""
    reasoning_effort: str = ""
    self_check: bool = True


class ConversationUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    target: str | None = None
    autonomous: bool | None = None
    self_check: bool | None = None


class ConversationMessage(BaseModel):
    message: str
    confirm: dict | None = None


@router.post("/api/chat")
def chat(request: ChatRequest):
    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM 未配置；请在设置里填写 API Key")
    try:
        template = from_dict(Template, request.template)
        validate_template(template)
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc

    try:
        registry = rt._registry_for(template)
        with tempfile.TemporaryDirectory() as td:
            log = EventLog(Path(td) / "session.jsonl")
            agent = ChatAgent(provider, template, registry, log)
            result = agent.respond(request.message, request.history, initial_facts=request.facts)
            events = [{"seq": e.seq, "type": e.type, "data": e.data} for e in log.read()]
    except ApprovalDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = uuid.uuid4().hex
    rt._active().save_run(run_id, {
        "id": run_id,
        "template_id": template.id,
        "target": request.message,
        "kind": "chat",
        "output": result["content"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "facts": result["facts"],
        "events": events,
    })
    return {"run_id": run_id, "content": result["content"], "facts": result["facts"], "events": events}


@router.post("/api/assistant")
def assistant(request: AssistantRequest):
    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM 未配置；请在设置里填写 API Key")
    try:
        store = rt._projects_store()
        with tempfile.TemporaryDirectory() as td:
            log = EventLog(Path(td) / "session.jsonl")
            agent = AssistantAgent(provider, store, log, template_store=rt._template_store, tool_store=rt._tool_store, skill_store=rt._skill_store)
            result = agent.respond(request.message, request.history, confirm=request.confirm)
            events = [{"seq": e.seq, "type": e.type, "data": e.data} for e in log.read()]
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"content": result["content"], "events": events}


def _require_conversation(conv_id):
    conv = rt._active().get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.get("/api/conversations")
def list_conversations():
    return {"conversations": [c for c in rt._active().conversations if not c.get("deleted_at") and not c.get("is_default")]}


@router.post("/api/conversations")
def create_conversation(body: ConversationCreate):
    if body.kind not in ("assistant", "task"):
        raise HTTPException(status_code=400, detail="kind must be assistant or task")
    project = rt._active()
    conv = {
        "id": f"conv_{uuid.uuid4().hex[:8]}",
        "name": body.name or ("assistant" if body.kind == "assistant" else "task"),
        "kind": body.kind,
        "template_id": body.template_id,
        "model": body.model,
        "reasoning_effort": body.reasoning_effort,
        "project_id": project.id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "messages": [],
        "target": "",
        "autonomous": False,
        "self_check": body.self_check,
        "last_run_id": "",
    }
    project.upsert_conversation(conv)
    return conv


@router.put("/api/conversations/{conv_id}")
def update_conversation(conv_id: str, body: ConversationUpdate):
    conv = _require_conversation(conv_id)
    for field in ("name", "model", "reasoning_effort", "target", "autonomous", "self_check"):
        value = getattr(body, field)
        if value is not None:
            conv[field] = value
    conv["updated_at"] = datetime.now().isoformat(timespec="seconds")
    rt._active().upsert_conversation(conv)
    return conv


@router.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    _require_conversation(conv_id)
    rt._active().delete_conversation(conv_id)
    return {"deleted": conv_id}


@router.post("/api/conversations/{conv_id}/messages")
def conversation_message(conv_id: str, body: ConversationMessage):
    conv = _require_conversation(conv_id)
    provider = rt._get_provider_for(conv.get("model", ""), conv.get("reasoning_effort", ""))
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM not configured; set API key in settings")
    if conv["kind"] != "assistant":
        raise HTTPException(status_code=400, detail="task conversations must use /api/runs")
    template_data = rt._template_store.get(conv.get("template_id", "")) if conv.get("template_id") else None
    template = from_dict(Template, template_data) if template_data else None
    store = rt._projects_store()
    with tempfile.TemporaryDirectory() as td:
        log = EventLog(Path(td) / "session.jsonl")
        agent = AssistantAgent(
            provider, store, log,
            template_store=rt._template_store,
            tool_store=rt._tool_store,
            skill_store=rt._skill_store,
            template=template,
        )
        result = agent.respond(body.message, conv.get("messages", []), confirm=body.confirm)
        events = [{"seq": e.seq, "type": e.type, "data": e.data} for e in log.read()]
    messages = list(conv.get("messages", []))
    if body.message.strip():
        messages.append({"role": "user", "content": body.message})
    messages.append({"role": "assistant", "content": result.get("content") or ""})
    conv["messages"] = messages
    conv["updated_at"] = datetime.now().isoformat(timespec="seconds")
    rt._active().upsert_conversation(conv)
    return {"content": result.get("content"), "events": events, "pending": result.get("pending")}


@router.post("/api/conversations/{conv_id}/messages/stream")
def conversation_stream(conv_id: str, body: ConversationMessage):
    conv = _require_conversation(conv_id)
    if conv["kind"] != "assistant":
        raise HTTPException(status_code=400, detail="task conversations must use /api/runs")
    provider = rt._get_provider_for(conv.get("model", ""), conv.get("reasoning_effort", ""))
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM not configured; set API key in settings")
    job_id = uuid.uuid4().hex
    with rt._live_lock:
        rt._live_runs[job_id] = rt._LiveRun()
    thread = threading.Thread(
        target=rt._run_conversation_stream,
        args=(conv_id, job_id, body.message, body.confirm),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@router.get("/api/conversations/{conv_id}/messages/stream/{job_id}/events")
async def conversation_stream_events(conv_id: str, job_id: str):
    if rt._get_live(job_id) is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return StreamingResponse(rt._conv_stream_events(conv_id, job_id), media_type="text/event-stream")


