"""Assets & groups routes (extracted from server.py)."""
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




class GroupCreate(BaseModel):
    kind: str
    name: str


class GroupRename(BaseModel):
    kind: str
    name: str


class GroupMembers(BaseModel):
    kind: str
    members: list[str] = []


def _groups_for(kind: str):
    if kind not in ("tool", "skill"):
        raise HTTPException(status_code=400, detail="kind 必须是 tool 或 skill")
    return "tool_groups" if kind == "tool" else "skill_groups"


@router.get("/api/groups")
def list_groups():
    return rt._active().asset_groups


@router.post("/api/groups")
def create_group(body: GroupCreate):
    key = _groups_for(body.kind)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    project = rt._active()
    groups = project.asset_groups
    if any(g["name"] == name for g in groups[key]):
        raise HTTPException(status_code=400, detail="分组名称已存在")
    group = {"id": next_group_id(body.kind, groups[key]), "name": name, "members": []}
    groups[key].append(group)
    project.save_asset_groups()
    return group


@router.put("/api/groups/{group_id}")
def rename_group(group_id: str, body: GroupRename):
    key = _groups_for(body.kind)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    project = rt._active()
    groups = project.asset_groups
    group = next((g for g in groups[key] if g["id"] == group_id), None)
    if group is None:
        raise HTTPException(status_code=404, detail="group not found")
    if any(g["id"] != group_id and g["name"] == name for g in groups[key]):
        raise HTTPException(status_code=400, detail="分组名称已存在")
    group["name"] = name
    project.save_asset_groups()
    return group


@router.delete("/api/groups/{group_id}")
def delete_group(group_id: str, kind: str = Query(...)):
    key = _groups_for(kind)
    project = rt._active()
    groups = project.asset_groups
    if not any(g["id"] == group_id for g in groups[key]):
        raise HTTPException(status_code=404, detail="group not found")
    groups[key] = [g for g in groups[key] if g["id"] != group_id]
    project.save_asset_groups()
    return {"deleted": group_id}


@router.put("/api/groups/{group_id}/members")
def set_group_members(group_id: str, body: GroupMembers):
    key = _groups_for(body.kind)
    project = rt._active()
    groups = project.asset_groups
    group = next((g for g in groups[key] if g["id"] == group_id), None)
    if group is None:
        raise HTTPException(status_code=404, detail="group not found")
    group["members"] = list(dict.fromkeys(body.members))
    project.save_asset_groups()
    return group


@router.get("/api/assets")
def list_assets(kind: str | None = None, q: str = "", run_id: str = "", session_id: str = ""):
    return {"assets": rt._active().assets.list_assets(kind=kind, query=q, run_id=run_id, session_id=session_id)}


@router.post("/api/assets/ingest")
def ingest_assets(body: dict):
    run_id = body.get("run_id", "")
    run = rt._active().runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    extracted, relations = extract_assets_from_facts(run.get("facts", {}), run_id)
    stats = {"added": 0, "updated": 0, "relations": 0}
    for asset in extracted:
        before = rt._active().assets.list_assets(kind=asset["kind"], query=asset["value"])
        rt._active().assets.upsert_asset(
            kind=asset["kind"],
            value=asset["value"],
            source_run_id=run_id,
            source_tool=asset.get("source_tool", ""),
            session_id=run.get("session_id", ""),
        )
        if before:
            stats["updated"] += 1
        else:
            stats["added"] += 1
    stats["relations"] = len(relations)
    return stats


@router.get("/api/assets/graph")
def asset_graph(root: str = "", limit: int = 200, session_id: str = ""):
    return rt._active().assets.graph(root_asset_id=root, limit=limit, session_id=session_id)


