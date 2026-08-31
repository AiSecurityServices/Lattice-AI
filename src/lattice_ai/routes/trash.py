"""Trash routes (extracted from server.py)."""
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




@router.get("/api/trash")
def list_trash():
    items = []
    items.extend(rt._template_store.trash_list())
    items.extend(rt._tool_store.trash_list())
    items.extend(rt._skill_store.trash_list())
    items.extend(rt._projects_store().trash_list())
    for conv in rt._active().trashed_conversations():
        items.append({
            "kind": "conversations",
            "name": conv.get("id", ""),
            # `name` doubles as the restore/purge key, so the friendly label
            # rides along separately.
            "display_name": conv.get("name", ""),
            "deleted_at": conv.get("deleted_at", ""),
        })
    items.sort(key=lambda item: item.get("deleted_at", ""), reverse=True)
    return {"items": items}


@router.post("/api/trash/{kind}/{name}/restore")
def restore_trash(kind: str, name: str):
    try:
        if kind == "templates":
            rt._template_store.restore(name)
        elif kind == "tools":
            rt._tool_store.restore(name)
        elif kind == "skills":
            rt._skill_store.restore(name)
        elif kind == "projects":
            rt._projects_store().restore_project(name)
        elif kind == "conversations":
            rt._active().restore_conversation(name)
        else:
            raise HTTPException(status_code=404, detail="unknown trash kind")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"trash item not found: {exc}") from exc
    return {"restored": name, "kind": kind}


@router.delete("/api/trash")
def empty_trash(kind: str | None = None):
    if kind in (None, "templates"):
        rt._template_store.empty_trash()
    if kind in (None, "tools"):
        rt._tool_store.empty_trash()
    if kind in (None, "skills"):
        rt._skill_store.empty_trash()
    if kind in (None, "projects"):
        rt._projects_store().empty_trash()
    if kind in (None, "conversations"):
        rt._active().empty_trash_conversations()
    return {"cleared": kind or "all"}


@router.delete("/api/trash/{kind}/{name}")
def purge_trash(kind: str, name: str):
    if kind == "templates":
        rt._template_store.purge(name)
    elif kind == "tools":
        rt._tool_store.purge(name)
    elif kind == "skills":
        rt._skill_store.purge(name)
    elif kind == "projects":
        rt._projects_store().purge_project(name)
    elif kind == "conversations":
        rt._active().purge_conversation(name)
    else:
        raise HTTPException(status_code=404, detail="unknown trash kind")
    return {"purged": name, "kind": kind}


