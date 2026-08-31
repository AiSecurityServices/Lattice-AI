"""Marketplace & modules routes (extracted from server.py)."""
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




@router.get("/api/marketplace")
def list_marketplace():
    from lattice_ai.tool_import import template_dependencies

    items = []
    for k, v in rt._MARKETPLACE.items():
        reqs = v.get("requires_tools", [])
        installed = {}
        for name in reqs:
            tool = next((t for t in rt._VULN_TOOLS if t["name"] == name), None)
            if tool and rt.find_executable(tool["command"][0]):
                installed[name] = True
            else:
                installed[name] = False
        items.append({
            "id": k,
            "name": v["name"],
            "name_i18n": v.get("name_i18n"),
            "description": v["description"],
            "description_i18n": v.get("description_i18n"),
            "needs_tools": reqs,
            "tools_installed": installed,
            # Pre-install sheet so the UI can render what the template needs
            # (secrets to prepare, executables, approval decisions) before
            # the user confirms the install.
            "dependencies": template_dependencies(v.get("template") or {}),
        })
    return {"templates": items}


@router.get("/api/modules")
def list_modules():
    return list_marketplace()



@router.post("/api/marketplace/{template_id}/install")
def install_marketplace(template_id: str):
    if template_id not in rt._MARKETPLACE:
        raise HTTPException(status_code=404, detail="marketplace template not found")
    entry = rt._MARKETPLACE[template_id]
    tpl = entry["template"]
    try:
        parsed = from_dict(Template, tpl)
        validate_template(parsed)
        rt._registry_for(parsed)
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rt._template_store.save(template_id, to_dict(parsed))
    requires = entry.get("requires_tools", [])
    if not requires:
        return {"id": template_id, "name": parsed.name, "tools_installed": {}, "tool_results": []}
    job_id = uuid.uuid4().hex[:12]
    with rt._install_lock:
        rt._install_jobs[job_id] = {"job_id": job_id, "status": "installing", "results": [], "error": None}
    threading.Thread(target=rt._run_install_job, args=(job_id, requires), daemon=True).start()
    return {
        "id": template_id,
        "name": parsed.name,
        "job_id": job_id,
        "status": "installing",
    }


@router.get("/api/marketplace/install/{job_id}")
def install_status(job_id: str):
    with rt._install_lock:
        state = rt._install_jobs.get(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="install job not found")
        results = list(state["results"])
        status = state["status"]
        error = state["error"]
    installed = {r["name"]: r["status"] in {"installed", "already_installed"} for r in results}
    return {"job_id": job_id, "status": status, "results": results, "error": error, "tools_installed": installed}


