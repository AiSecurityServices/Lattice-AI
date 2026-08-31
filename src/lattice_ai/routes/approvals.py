"""Approvals routes (extracted from server.py)."""
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




@router.post("/api/approvals")
def create_approval(body: dict):
    rt._projects_store()  # force the lazy project store so approvals bind to SQLite, not memory
    # Optional tool payload (lenient per contract): a "tool_payload" key, or a
    # "tool" key whose value is a dict. Passing it lets /api/tools/try/execute
    # run the call later without ever involving /api/tools/try (which needs
    # the LLM to map a target onto args).
    name = body.get("tool", "")
    tool_payload = body.get("tool_payload")
    if not isinstance(tool_payload, dict) and isinstance(body.get("tool"), dict):
        tool_payload = body.get("tool")
        name = body.get("tool_name") or tool_payload.get("name") or ""
    return {"approval_id": approval_create_pending(name, body.get("args", {}), tool=tool_payload)}


@router.post("/api/approvals/{approval_id}/resolve")
def resolve_approval(approval_id: str, body: dict):
    rt._projects_store()
    try:
        return approval_resolve_pending(approval_id, bool(body.get("approved")), str(body.get("reason") or ""))
    except KeyError:
        raise HTTPException(status_code=404, detail="approval not found")


@router.get("/api/approvals")
def list_approvals():
    rt._projects_store()
    return {"approvals": rt._active().approval_logs}


