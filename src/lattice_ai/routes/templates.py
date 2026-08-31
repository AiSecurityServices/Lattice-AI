"""Template routes (extracted from server.py)."""
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




class GenerateRequest(BaseModel):
    source: str = ""
    mode: str = ""
    description: str = ""
    name: str = ""


@router.get("/api/templates")
def list_templates():
    # Cold start: the matrix/builtin templates are seeded when the project
    # store initializes, which only this call chain triggers — without it a
    # fresh backend's first template list would be empty.
    rt._projects_store()
    templates = rt._template_store.list()
    return {"templates": [{"id": t["id"], "name": t.get("name")} for t in templates]}


@router.get("/api/templates/{template_id}")
def get_template(template_id: str):
    template = rt._template_store.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    return template


@router.put("/api/templates/{template_id}")
def put_template(template_id: str, template: dict):
    try:
        parsed = from_dict(Template, template)
        if parsed.id != template_id:
            raise HTTPException(status_code=400, detail="template id does not match path")
        validate_template(parsed)
        rt._registry_for(parsed)
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc
    except HTTPException:
        raise
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rt._template_store.save(template_id, to_dict(parsed))
    return {"id": template_id, "name": parsed.name}


@router.delete("/api/templates/{template_id}")
def delete_template(template_id: str):
    if rt._template_store.get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    rt._template_store.delete(template_id)
    return {"deleted": template_id}


@router.post("/api/templates/generate")
def generate_from_source(body: GenerateRequest):
    if not body.source.strip() and not body.description.strip():
        raise HTTPException(status_code=400, detail="需要提供 source（URL/路径）或 description（自然语言描述）")
    job_id = start_generation(body.model_dump())
    return {"job_id": job_id}


@router.get("/api/templates/generate/{job_id}/events")
async def generate_events(job_id: str):
    if not generation_exists(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return StreamingResponse(rt._job_event_stream(job_id), media_type="text/event-stream")


@router.post("/api/templates/{template_id}/clone")
def clone_template(template_id: str):
    source = rt._template_store.get(template_id)
    if source is None:
        raise HTTPException(status_code=404, detail="template not found")
    clone_id = f"{template_id}-copy-{uuid.uuid4().hex[:6]}"
    return rt._template_store.clone(template_id, clone_id)


@router.post("/api/templates/{template_id}/rename")
def rename_template(template_id: str, body: dict):
    if rt._template_store.get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    name = rt._require_str(body.get("name"), "name")
    rt._template_store.rename(template_id, name)
    return {"id": template_id, "name": name}


@router.post("/api/templates/{template_id}/refine")
def refine_template(template_id: str, body: dict):
    template_data = rt._template_store.get(template_id)
    if template_data is None:
        raise HTTPException(status_code=404, detail="template not found")
    template = from_dict(Template, template_data)
    applied, rejected = [], []
    for suggestion in body.get("suggestions") or []:
        try:
            template = apply_suggestion(template, suggestion)
            applied.append(suggestion)
        except (KeyError, ValueError) as exc:
            rejected.append({"suggestion": suggestion, "reason": str(exc)})
    new_version = rt._template_store.save_versioned(
        template_id, to_dict(template), lineage={"source": "refine", "ref_id": ""}
    )
    return {"new_version": new_version, "applied": applied, "rejected": rejected, "template": to_dict(template)}


@router.get("/api/templates/{template_id}/history")
def template_history(template_id: str):
    return {"versions": rt._template_store.list_history(template_id)}


@router.get("/api/templates/{template_id}/versions")
def list_template_versions(template_id: str, offset: int = 0, limit: int = Query(50, ge=1, le=200)):
    if rt._template_store.get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    return rt._template_store.list_versions(template_id, offset=offset, limit=limit)


@router.get("/api/templates/{template_id}/versions/{version}")
def get_template_version(template_id: str, version: int):
    data = rt._template_store.get_version(template_id, version)
    if data is None:
        raise HTTPException(status_code=404, detail="version not found")
    return {
        "version": version,
        "lineage": rt._template_store.get_version_lineage(template_id, version),
        "template": data,
    }


@router.post("/api/templates/preview-suggestion")
def preview_suggestion(body: dict):
    """Evolution panel helper: apply one suggestion to a copy of the template
    and return the result so the UI can diff it without saving anything."""
    template_data = body.get("template")
    suggestion = body.get("suggestion") or {}
    if not isinstance(template_data, dict):
        raise HTTPException(status_code=400, detail="template is required")
    try:
        template = from_dict(Template, template_data)
        updated = apply_suggestion(template, suggestion)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": to_dict(updated)}


@router.get("/api/templates/{template_id}/evolution-runs")
def list_evolution_runs(template_id: str, limit: int = Query(10, ge=1, le=50)):
    """Recent runs of this template that carry self-check suggestions, for the
    TemplatesPage 'improvement suggestions' entry."""
    if rt._template_store.get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    items = []
    for run in rt._active().runs.values():
        if run.get("template_id") != template_id:
            continue
        evolution = run.get("evolution") or {}
        suggestions = evolution.get("suggestions") or []
        if not suggestions:
            continue
        items.append({
            "run_id": run.get("id", ""),
            "created_at": run.get("created_at", ""),
            "target": run.get("target", ""),
            "summary": evolution.get("summary", ""),
            "suggestion_count": len(suggestions),
        })
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return {"runs": items[:limit]}


@router.post("/api/templates/{template_id}/versions/batch")
def get_template_versions_batch(template_id: str, body: dict):
    if rt._template_store.get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    requested = [int(v) for v in (body.get("versions") or [])][:20]
    out = []
    for version in requested:
        data = rt._template_store.get_version(template_id, version)
        if data is None:
            continue
        out.append({
            "version": version,
            "lineage": rt._template_store.get_version_lineage(template_id, version),
            "template": data,
        })
    return {"versions": out}


@router.post("/api/templates/{template_id}/versions/{version}/restore")
def restore_template_version(template_id: str, version: int):
    """n8n-style restore: copy the historical version on top of the chain as a
    new version; existing history entries are never rewritten."""
    try:
        new_version = rt._template_store.rollback(template_id, version)
    except KeyError:
        raise HTTPException(status_code=404, detail="version not found") from None
    return {"new_version": new_version, "template": rt._template_store.get(template_id)}


@router.post("/api/templates/{template_id}/rollback/{version}")
def rollback_template(template_id: str, version: int):
    try:
        new_version = rt._template_store.rollback(template_id, version)
    except KeyError:
        raise HTTPException(status_code=404, detail="version not found") from None
    return {
        "new_version": new_version,
        "template": rt._template_store.get(template_id),
        "deprecation": "rollback is copy-as-new-version; prefer POST /api/templates/{id}/versions/{version}/restore",
    }


@router.get("/api/templates/{template_id}/tools")
def list_template_tools(template_id: str):
    template = rt._template_store.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    return {"tools": template.get("tools", [])}


@router.put("/api/templates/{template_id}/tools/{name}")
def put_template_tool(template_id: str, name: str, body: dict):
    template = rt._template_store.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    tools = [t for t in template.get("tools", []) if t.get("name") != name]
    tools.append(body)
    template["tools"] = tools
    rt._template_store.save(template_id, template)
    return {"template_id": template_id, "tools": tools}


@router.delete("/api/templates/{template_id}/tools/{name}")
def delete_template_tool(template_id: str, name: str):
    template = rt._template_store.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    template["tools"] = [t for t in template.get("tools", []) if t.get("name") != name]
    rt._template_store.save(template_id, template)
    return {"deleted": name}


@router.get("/api/templates/{template_id}/skills")
def list_template_skills(template_id: str):
    template = rt._template_store.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    return {"skills": template.get("skills", [])}


@router.put("/api/templates/{template_id}/skills/{name}")
def put_template_skill(template_id: str, name: str, body: dict):
    template = rt._template_store.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    skills = [s for s in template.get("skills", []) if s.get("name") != name]
    skills.append(body)
    template["skills"] = skills
    rt._template_store.save(template_id, template)
    return {"template_id": template_id, "skills": skills}


@router.delete("/api/templates/{template_id}/skills/{name}")
def delete_template_skill(template_id: str, name: str):
    template = rt._template_store.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    template["skills"] = [s for s in template.get("skills", []) if s.get("name") != name]
    rt._template_store.save(template_id, template)
    return {"deleted": name}


