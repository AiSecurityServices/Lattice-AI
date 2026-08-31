"""Tool routes (extracted from server.py)."""
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




class ImportApply(BaseModel):
    template_id: str = ""
    preview: dict
    accepted_assets: list[dict] = []
    bindings: list[dict] = []


def _tool_usage(tool: dict) -> str:
    if tool.get("runner") == "builtin":
        return "builtin"
    if tool.get("runner") == "adapter":
        return tool.get("adapter") or "adapter"
    return tool.get("runner") or "cli"


@router.get("/api/tools")
def list_tools():
    from lattice_ai import toolchain_registry as tcr

    registry = ToolRegistry()
    rt.install_builtins(registry)
    registry_meta = {e.name: e for e in tcr.load_registry()}
    tools = []
    for t in registry.list_tools():
        item = {**to_dict(t), "builtin": True, "available": True, "status": "builtin"}
        entry = registry_meta.get(t.name)
        if entry is not None and t.runner == "cli":
            installed = rt.find_real_executable(t.name) is not None
            item["status"] = "installed" if installed else "missing"
            item["version"] = tcr.registry_version(entry) if installed else None
            item["tier_hint"] = "real" if installed else ("sim" if entry.builtin_fallback else "unavailable")
            item["danger"] = entry.danger
            item["registry"] = True
        item["capability"] = capability_of(t)
        item["usage"] = _tool_usage(item)
        tools.append(item)
    for t in rt._tool_store.list():
        tool = from_dict(Tool, t)
        meta = {
            **to_dict(tool),
            "builtin": False,
            "available": tool_available(tool),
            "status": tool_status(tool),
        }
        # A stored recipe sharing a registry name is a user view of the same
        # tool; runtime uses the registry entry, so surface registry metadata.
        entry = registry_meta.get(tool.name)
        if entry is not None:
            installed = rt.find_real_executable(tool.name) is not None
            meta["status"] = "installed" if installed else "missing"
            meta["version"] = tcr.registry_version(entry) if installed else None
            meta["tier_hint"] = "real" if installed else ("sim" if entry.builtin_fallback else "unavailable")
            meta["danger"] = entry.danger
            meta["registry"] = True
        meta["capability"] = capability_of(tool)
        meta["usage"] = _tool_usage(meta)
        idx = next((i for i, item in enumerate(tools) if item["name"] == meta["name"]), None)
        if idx is None:
            tools.append(meta)
        elif meta.get("runner") != "builtin":
            # A stored cli/adapter tool shadows the same-name builtin fallback.
            tools[idx] = meta
    return {"tools": tools}


@router.post("/api/tools/import")
def import_tool(body: dict):
    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM provider not configured; set LATTICE_API_KEY")
    description = body.get("description", "")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    try:
        draft = generate_tool_draft(provider, description)
        tool = from_dict(Tool, draft)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"import failed: {exc}") from exc
    return {"yaml": tool_to_yaml(tool)}


@router.post("/api/tools/recipes")
def save_recipe(body: dict):
    text = body.get("yaml", "")
    try:
        tool = yaml_to_tool(text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid recipe: {exc}") from exc
    try:
        tool.name = rt._require_str(tool.name, "name")
    except HTTPException:
        raise
    rt._tool_store.save(tool.name, to_dict(tool))
    return {"name": tool.name}


@router.delete("/api/tools/recipes/{name}")
def delete_recipe(name: str):
    if not any(t["name"] == name for t in rt._tool_store.list()):
        raise HTTPException(status_code=404, detail="recipe not found")
    rt._tool_store.delete(name)
    return {"deleted": name}


@router.put("/api/tools/{name}")
def update_tool(name: str, body: dict):
    if not any(t["name"] == name for t in rt._tool_store.list()):
        raise HTTPException(status_code=404, detail="tool not found")
    try:
        tool = from_dict(Tool, body)
        if tool.name != name:
            raise ValueError("tool name does not match path")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid tool: {exc}") from exc
    rt._tool_store.save(name, to_dict(tool))
    return {"name": name}


@router.post("/api/tools/run")
def run_tool(body: dict):
    try:
        tool = from_dict(Tool, body.get("tool", {}))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid tool: {exc}") from exc
    args = body.get("args", {})
    registry = rt._manual_registry(tool, args)
    try:
        registry.register(tool)
        result = registry.run(tool.name, args, approver=None)
    except ApprovalDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/api/tools/import-mcp")
def import_mcp(body: dict):
    source = body.get("source", "")
    provider = rt._get_provider()
    if not detect_mcp(source, provider):
        raise HTTPException(status_code=400, detail="not recognized as MCP")
    command = parse_command(source)
    try:
        tools = list_mcp_tools(command)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to discover MCP tools: {exc}") from exc
    drafts = mcp_tools_to_lattice(tools, command=command)
    return {"tools": [to_dict(t) for t in drafts]}


@router.post("/api/tools/import-source")
def import_source(body: dict):
    source = body.get("source", "")
    kind = classify_source(source)
    provider = rt._get_provider()
    if kind != "mcp" and provider is None:
        raise HTTPException(status_code=400, detail="LLM not configured")
    try:
        tools = import_tool_source(provider, source)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to import source: {exc}") from exc
    return {"tools": [to_dict(t) for t in tools]}


@router.post("/api/tools/imported")
def save_imported_tool(body: dict):
    try:
        tool = from_dict(Tool, body.get("tool", {}))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid tool: {exc}") from exc
    rt._tool_store.save(tool.name, to_dict(tool))
    return {"name": tool.name}


@router.post("/api/tools/try")
def try_imported_tool(body: dict):
    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM not configured")
    try:
        tool = from_dict(Tool, body["tool"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid tool: {exc}") from exc
    target = body.get("target", "")
    args = map_target_to_args(provider, tool, target)
    approval_id = approval_create_pending(tool.name, args, tool=to_dict(tool))
    return {"approval_id": approval_id, "tool": tool.name, "args": args}


@router.post("/api/tools/try/execute")
def execute_imported_tool(body: dict):
    approval_id = body.get("approval_id", "")
    try:
        pending = approval_get_pending(approval_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="approval not found")
    if pending["status"] == "pending":
        raise HTTPException(status_code=400, detail="approval still pending")
    if pending["status"] != "approved":
        raise HTTPException(status_code=403, detail="approval was denied")
    tool_data = pending.get("tool_payload")
    if not tool_data:
        raise HTTPException(status_code=400, detail="approval has no tool payload")
    tool = from_dict(Tool, tool_data)
    args = pending.get("args") or {}
    registry = rt._manual_registry(tool, args)
    try:
        registry.register(tool)
        result = registry.run(tool.name, args, approver=lambda tool, run_args: True)
    except (ApprovalDenied, ToolError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider = rt._get_provider()
    evidence_id = f"evt_trial_{uuid.uuid4().hex[:8]}"
    rt._active().save_evidence(evidence_id, {
        "id": evidence_id,
        "run_id": "trial",
        "stage_id": "trial",
        "tool": tool.name,
        "result": result,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "hash": hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest(),
    })
    # Findings/report are LLM niceties on top of the trial: without a provider
    # (approvals built via POST /api/approvals, no /api/tools/try involved) the
    # execution result itself is still returned.
    findings: list = []
    report = None
    if provider is not None:
        facts = {tool.name: result}
        minimal_template = {"name": "导入工具试运行", "stages": [], "tools": []}
        target = str((pending.get("args") or {}).get("target", ""))
        findings = rt.generate_findings(provider, facts, minimal_template, target=target)
        report = rt.generate_report(provider, facts, minimal_template)
    return {"tool": tool.name, "result": result, "evidence": evidence_id, "findings": findings, "report": report}


@router.post("/api/tools/{name}/bind")
def bind_imported_tool(name: str, body: dict):
    template_id = body.get("template_id", "")
    stage_id = body.get("stage_id")
    template_data = rt._template_store.get(template_id)
    if template_data is None:
        raise HTTPException(status_code=404, detail="template not found")
    template = from_dict(Template, template_data)
    tool_data = rt._tool_store.get(name)
    if tool_data is None:
        raise HTTPException(status_code=404, detail="imported tool not found")
    if not any(t.name == name for t in template.tools):
        template.tools.append(from_dict(Tool, tool_data))
    if stage_id:
        stage = next((s for s in template.stages if s.id == stage_id), None)
        if stage is None:
            raise HTTPException(status_code=404, detail="stage not found")
        if not any(b.tool == name for b in stage.tools):
            stage.tools.append(ToolBinding(tool=name))
    rt._template_store.save(template_id, to_dict(template))
    return {"template_id": template_id, "tool": name}


@router.post("/api/tools/import-asset")
def import_asset(body: dict):
    source = body.get("source", "")
    preview = preview_asset_import(rt._get_provider(), source)
    return preview.__dict__


@router.post("/api/tools/import-asset/apply")
def apply_asset_import(body: ImportApply):
    preview = body.preview
    template_id = body.template_id or preview.get("template_id", "")
    template_data = rt._template_store.get(template_id)
    template = from_dict(Template, template_data) if template_data else None

    results = {"skills": [], "tools": [], "bindings": []}
    for asset in body.accepted_assets:
        if asset.get("type") == "skill":
            skill = from_dict(Skill, {
                "name": asset.get("name", ""),
                "description": asset.get("description", ""),
                "content": asset.get("content", ""),
            })
            rt._skill_store.save(skill.name, to_dict(skill))
            results["skills"].append(skill.name)
        elif asset.get("type") == "tool":
            tool = from_dict(Tool, asset.get("data") or {
                "name": asset.get("name", ""),
                "description": asset.get("description", ""),
                "runner": "cli",
                "approval": "allow",
            })
            rt._tool_store.save(tool.name, to_dict(tool))
            results["tools"].append(tool.name)

    if template is not None:
        for binding in body.bindings:
            tool_name = binding.get("tool", "")
            stage_id = binding.get("stage_id")
            if not any(t.name == tool_name for t in template.tools):
                template.tools.append(from_dict(Tool, rt._tool_store.get(tool_name) or {}))
            stage = next((s for s in template.stages if s.id == stage_id), None)
            if stage is not None and not any(b.tool == tool_name for b in stage.tools):
                stage.tools.append(ToolBinding(tool=tool_name))
            results["bindings"].append({"tool": tool_name, "stage_id": stage_id})
        rt._template_store.save(template_id, to_dict(template))

    return results


