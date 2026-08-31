"""Project routes (extracted from server.py)."""
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




class ProjectCreate(BaseModel):
    name: str


class ProjectSwitch(BaseModel):
    id: str


class TemplateSwitch(BaseModel):
    template_id: str


@router.get("/api/projects")
def list_projects():
    store = rt._projects_store()
    return {"projects": store.list(), "current": store.current}


@router.post("/api/projects")
def create_project(body: ProjectCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    project = rt._projects_store().create(name)
    return {"id": project.id, "name": project.name}


@router.put("/api/projects/current")
def switch_project(body: ProjectSwitch):
    store = rt._projects_store()
    try:
        store.switch(body.id)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    return {"current": store.current}


@router.get("/api/projects/current")
def get_current_project():
    project = rt._projects_store().active()
    return {
        "id": project.id,
        "name": project.name,
        "current_template_id": project.current_template_id,
        "settings": rt._redact_settings(project.settings),
    }


@router.put("/api/projects/current/template")
def set_current_template(body: TemplateSwitch):
    if rt._template_store.get(body.template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    project = rt._projects_store().active()
    project.save_current_template_id(body.template_id)
    return {"id": project.id, "current_template_id": project.current_template_id}


@router.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = rt._projects_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {
        "id": project.id,
        "name": project.name,
        "current_template_id": project.current_template_id,
        "counts": {
            "runs": len(project.runs),
            "evidence": len(project.evidence),
            "findings": len(project.findings),
        },
    }


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    store = rt._projects_store()
    try:
        store.delete(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": project_id}


@router.post("/api/projects/{project_id}/rename")
def rename_project(project_id: str, body: dict):
    project = rt._projects_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    name = rt._require_str(body.get("name"), "name")
    project.save_meta(name)
    return {"id": project_id, "name": name}


