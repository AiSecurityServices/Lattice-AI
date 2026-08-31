"""Settings / scope / security / preferences / toolchain / providers routes (extracted from server.py)."""
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




class ScopePut(BaseModel):
    allow_domains: list[str] = []
    allow_ips: list[str] = []
    allow_cidrs: list[str] = []
    allow_ports: list[int] = []
    allow_url_prefixes: list[str] = []


class SecurityPut(BaseModel):
    level: str
    whitelist: list[dict] = []


@router.get("/api/scope")
def get_scope():
    policy = scope_policy_from_dict(rt._active().scope_policy)
    return {
        "allow_domains": policy.allow_domains,
        "allow_ips": policy.allow_ips,
        "allow_cidrs": policy.allow_cidrs,
        "allow_ports": policy.allow_ports,
        "allow_url_prefixes": policy.allow_url_prefixes,
    }


@router.put("/api/scope")
def put_scope(body: ScopePut):
    policy = body.model_dump()
    rt._active().save_scope_policy(policy)
    return policy


@router.get("/api/settings/security")
def get_security_settings():
    policy = rt._active().danger_policy or {}
    return {"level": policy.get("level", "lenient"), "whitelist": policy.get("whitelist", [])}


@router.put("/api/settings/security")
def put_security_settings(body: SecurityPut):
    policy = {"level": body.level, "whitelist": body.whitelist}
    rt._active().save_danger_policy(policy)
    return policy


@router.get("/api/preferences")
def get_preferences():
    return load_preferences()


@router.put("/api/preferences")
def put_preferences(body: dict):
    try:
        return save_preferences(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/toolchain/registry")
def toolchain_registry():
    from lattice_ai import toolchain_registry as tcr
    return {"registry": tcr.registry_view()}


@router.get("/api/toolchain")
def list_toolchain():
    tools = []
    for name in rt._TOOLCHAIN_NAMES:
        available = rt.find_executable(name) is not None
        tools.append({"name": name, "available": available, "status": "installed" if available else "missing"})
    return {"tools": tools}


@router.post("/api/toolchain/install")
def install_toolchain_api(body: dict):
    tools = [t.strip() for t in body.get("tools", []) if isinstance(t, str) and t.strip()]
    if not tools:
        raise HTTPException(status_code=422, detail="tools is required")
    job_id = uuid.uuid4().hex[:12]
    with rt._install_lock:
        rt._install_jobs[job_id] = {"job_id": job_id, "status": "installing", "results": [], "error": None}
    threading.Thread(target=rt._run_install_job, args=(job_id, tools), daemon=True).start()
    return {"job_id": job_id, "status": "installing"}


@router.get("/api/toolchain/install/{job_id}")
def toolchain_install_status(job_id: str):
    with rt._install_lock:
        state = rt._install_jobs.get(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="install job not found")
        results = list(state["results"])
        status = state["status"]
        error = state["error"]
    installed = {r["name"]: r["status"] in {"installed", "already_installed"} for r in results}
    return {"job_id": job_id, "status": status, "results": results, "error": error, "tools_installed": installed}


@router.get("/api/settings")
def get_settings():
    return rt._redact_settings(rt._active().settings)



@router.get("/api/providers")
def list_providers():
    return {
        "providers": rt._PROVIDERS
    }


def _reasoning_efforts(provider, models):
    union = []
    for m in models:
        for e in (m.get("reasoning_efforts") or []):
            if e and e not in union:
                union.append(e)
    if union:
        return union
    return (rt._PROVIDERS.get(provider, {}) or {}).get("reasoning", {}).get("efforts", [])


def _infer_provider(base_url: str) -> str:
    text = (base_url or "").lower()
    if "deepseek" in text:
        return "deepseek"
    if "openai" in text:
        return "openai"
    return "custom"



@router.get("/api/models")
def list_api_models(base_url: str | None = None, api_key: str | None = None):
    settings = rt._active().settings
    url = base_url or settings.get("base_url", "")
    key = api_key or settings.get("api_key", "")
    if not key:
        raise HTTPException(status_code=400, detail="LLM not configured; set API key in settings")
    provider = _infer_provider(url)
    try:
        models = rt.list_models(url, key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to list models: {exc}") from exc
    return {"provider": provider, "models": [m["id"] for m in models], "efforts": _reasoning_efforts(provider, models)}


@router.post("/api/settings/test")
def test_provider(body: dict):
    stored = rt._active().settings
    base_url = body.get("base_url") or stored.get("base_url", "")
    api_key = body.get("api_key") or stored.get("api_key", "")
    model = body.get("model") or stored.get("model", "")
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="请填写 Base URL 和 API Key")
    provider = OpenAICompatibleProvider(base_url, api_key, model)
    return {"ok": provider.test()}


@router.put("/api/settings")
def put_settings(body: dict):
    settings = rt._active().settings
    for key in ("provider", "base_url", "model", "api_key", "reasoning_effort"):
        if key not in body:
            continue
        value = body[key]
        if value is not None and not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"{key} must be a string")
        if key == "api_key":
            if value:
                settings[key] = value
        else:
            settings[key] = value or ""
    rt._active().save_settings(settings)
    return rt._redact_settings(settings)


