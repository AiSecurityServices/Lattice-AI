"""Run & artifact routes (extracted from server.py)."""
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
from lattice_ai import approval
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




class RunRequest(BaseModel):
    template: dict
    target: str
    autonomous: bool = False
    self_check: bool = False
    danger_allowances: list[str] = []
    prior_run_id: str = ""
    session_id: str = ""


@router.get("/api/runs/{run_id}/evolution")
def get_run_evolution(run_id: str):
    run = rt._active().runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "evolution": run.get("evolution") or {}}


@router.get("/api/evidence")
def list_evidence(session_id: str = ""):
    items = [e for e in rt._active().evidence.values() if not session_id or e.get("session_id", "") == session_id]
    return {"evidence": items}


@router.get("/api/evidence/{evidence_id}")
def get_evidence(evidence_id: str):
    if evidence_id not in rt._active().evidence:
        raise HTTPException(status_code=404, detail="evidence not found")
    return rt._active().evidence[evidence_id]


@router.get("/api/findings")
def list_findings(session_id: str = ""):
    items = [f for f in rt._active().findings.values() if not session_id or f.get("session_id", "") == session_id]
    return {"findings": items}


@router.get("/api/findings/{finding_id}")
def get_finding(finding_id: str):
    if finding_id not in rt._active().findings:
        raise HTTPException(status_code=404, detail="finding not found")
    return rt._active().findings[finding_id]


@router.patch("/api/findings/{finding_id}")
def patch_finding(finding_id: str, body: dict):
    finding = rt._active().findings.get(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    for key in ("status", "confidence", "severity", "cwe", "cvss"):
        if key in body and body[key] is not None:
            finding[key] = body[key]
    rt._active().save_finding(finding_id, finding)
    return finding


@router.get("/api/logs")
def list_logs():
    lines = []
    for run_id, run in rt._active().runs.items():
        for event in run.get("events", []):
            lines.append({
                "run_id": run_id,
                "seq": event.get("seq"),
                "type": event.get("type"),
                "data": event.get("data"),
                "created_at": run.get("created_at"),
            })
    lines.sort(key=lambda item: (item.get("created_at") or "", item.get("seq") or 0))
    return {"logs": lines[-200:]}


@router.post("/api/runs")
def start_run(request: RunRequest):
    try:
        template = from_dict(Template, request.template)
        validate_template(template)
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc

    try:
        rt._registry_for(template)
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if rt._get_provider() is None:
        raise HTTPException(status_code=400, detail="LLM 未配置；请在设置里填写 API Key")

    if request.session_id:
        conv = rt._active().get_conversation(request.session_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        if request.target.strip():
            conv["messages"] = list(conv.get("messages", [])) + [{"role": "user", "content": request.target}]
            conv["updated_at"] = datetime.now().isoformat(timespec="seconds")
            rt._active().upsert_conversation(conv)

    prior_run_id = request.prior_run_id
    if not prior_run_id:
        prior_run_id = rt._latest_run_id_for_template(template.id)
    prior_context = None
    if prior_run_id:
        prior_run = rt._active().runs.get(prior_run_id)
        if prior_run:
            prior_context = build_run_context(prior_run, [
                f for f in rt._active().findings.values() if f.get("run_id") == prior_run_id
            ])

    run_id = uuid.uuid4().hex
    with rt._live_lock:
        rt._live_runs[run_id] = rt._LiveRun()
    thread = threading.Thread(
        target=rt._run_in_background,
        args=(run_id, template, request.target, request.autonomous, request.self_check, request.danger_allowances),
        kwargs={"prior_context": prior_context, "session_id": request.session_id},
        daemon=True,
    )
    thread.start()
    return {"id": run_id}


@router.post("/api/run")
def run(request: RunRequest):
    try:
        template = from_dict(Template, request.template)
        validate_template(template)
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc

    try:
        registry = rt._registry_for(template, danger_allowances=request.danger_allowances)
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM 未配置；请在设置里填写 API Key")

    run_id = uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory() as td:
            log = EventLog(Path(td) / "session.jsonl")
            if request.autonomous:
                facts = rt.WorkflowAgent(provider, registry, log, approver=None).run(template, request.target, cwd=rt._DATA_ROOT)
            else:
                agent = rt.StageAgent(
                    provider, registry, log, approver=None, skills={s.name: s.content for s in template.skills}
                )
                rs = Executor(
                    template, registry, log,
                    run_id=run_id,
                    checkpoint_path=rt._active().root / "sessions" / f"{run_id}.state.json",
                ).run(request.target, cwd=rt._DATA_ROOT, approver=None, agent=agent)
                facts = rs.facts
            events = [{"seq": e.seq, "type": e.type, "data": e.data} for e in log.read()]
    except ApprovalDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    recorded_findings = rt._recorded_findings_from_events(events)
    report_facts = {**facts, "recorded_findings": recorded_findings} if recorded_findings else facts
    report = None
    try:
        report = rt.generate_report(provider, report_facts, template)
    except Exception:
        report = None

    evolution = {}
    if request.self_check:
        try:
            selfcheck_units = group_units(events, autonomous=request.autonomous)
            unit_notes = [{"label": u["label"], "notes": self_check_unit(provider, u)} for u in selfcheck_units]
            evolution = evolution_report(provider, template, events, unit_notes)
        except Exception:
            evolution = {}

    rt._active().save_run(run_id, {
        "id": run_id,
        "template_id": template.id,
        "target": request.target,
        "kind": "run",
        "session_id": request.session_id,
        "output": None,
        "report": report,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "facts": facts,
        "events": events,
        "self_check": request.self_check,
        "evolution": evolution,
        "tool_tiers": rt._tool_tiers_from_events(events),
    })
    rt._save_evidence_from_events(rt._active(), run_id, events, session_id=request.session_id)
    rt._persist_evidence_tools(rt._active(), run_id, request.session_id, events)
    return {"id": run_id, "facts": facts, "events": events, "report": report, "self_check": request.self_check, "evolution": evolution}


@router.post("/api/run/preflight")
def preflight_run(body: dict):
    try:
        template = from_dict(Template, body.get("template", {}))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc
    target = body.get("target", "")
    project = rt._active()
    policy = project.danger_policy
    items = []
    for tool in template.tools:
        verdict = evaluate_danger(policy, tool, {"target": target})
        if verdict.action != "allow":
            items.append({
                "tool": tool.name,
                "category": verdict.category,
                "rule_id": verdict.rule_id,
                "action": verdict.action,
                "reason": verdict.reason,
            })
    scope_policy = scope_policy_from_dict(project.scope_policy)
    scope_ok, scope_reason = evaluate_scope(scope_policy, target)
    restricted = is_restricted_target(target)
    if restricted:
        scope_ok = False
        scope_reason = "target is restricted public infrastructure or a reserved range"

    # Registry cli tools that this template binds but that are not installed
    # (or whose PATH binary failed identity verification) — those with a
    # same-name sim will fall back; others fail that stage.
    from lattice_ai import toolchain_registry as tcr

    missing_tools = []
    for binding_tool in dict.fromkeys(
        b.tool for stage in template.stages for b in stage.tools if b.enabled
    ):
        tool_def = next((t for t in template.tools if t.name == binding_tool), None)
        runner = tool_def.runner if tool_def is not None else None
        entry = tcr.get_entry(binding_tool)
        if runner is None:
            if entry is None:
                continue  # unknown tool: executor reports the error itself
            runner = "cli"
        if runner != "cli":
            continue
        if rt.find_real_executable(binding_tool) is not None:
            continue
        missing_tools.append({
            "tool": binding_tool,
            "install_mode": ("manual" if entry and not entry.install_primary else "auto"),
            "hint": entry.install_manual if entry else "",
            "has_fallback": bool(entry.builtin_fallback) if entry else False,
        })

    return {
        "items": items,
        "scope": {
            "configured": scope_configured(scope_policy),
            "ok": scope_ok,
            "reason": scope_reason,
            "restricted": restricted,
        },
        "missing_tools": missing_tools,
    }


@router.get("/api/reports/{run_id}")
def export_run_report(run_id: str, format: str = Query("md")):
    fmt = format.lower()
    if fmt not in ("md", "html", "json"):
        raise HTTPException(status_code=400, detail="format must be md, html, or json")
    run = rt._active().runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    evidence = [v for v in rt._active().evidence.values() if v.get("run_id") == run_id]
    findings = [v for v in rt._active().findings.values() if v.get("run_id") == run_id]
    template_name = run.get("template_id", "workflow")
    body = export_report(run, evidence, findings, template_name, fmt)
    media_type = {"md": "text/markdown", "html": "text/html", "json": "application/json"}[fmt]
    return Response(content=body, media_type=media_type)


@router.get("/api/runs")
def list_runs(session_id: str = ""):
    runs = rt._active().runs
    return {
        "runs": [
            {
                "id": r["id"],
                "template_id": r["template_id"],
                "target": r["target"],
                "created_at": r.get("created_at"),
                "kind": r.get("kind", "run"),
                "output": r.get("output"),
            }
            for r in runs.values()
            if not session_id or r.get("session_id", "") == session_id
        ]
    }


@router.get("/api/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in rt._active().runs:
        raise HTTPException(status_code=404, detail="run not found")
    return rt._active().runs[run_id]


@router.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    if rt._get_live(run_id) is None and run_id not in rt._active().runs:
        raise HTTPException(status_code=404, detail="run not found")
    if rt._get_live(run_id) is not None:
        return StreamingResponse(rt._live_run_events(run_id), media_type="text/event-stream")
    return StreamingResponse(rt._stored_run_events(run_id), media_type="text/event-stream")


@router.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str):
    live = rt._get_live(run_id)
    if live is None:
        raise HTTPException(status_code=404, detail="run not found or not running")
    live.request_stop()
    # Don't leave approvals hanging on a run that is going away.
    approval.expire_run_pending(run_id)
    live.queue.put(("stopped", {"run_id": run_id}))
    return {"stopped": run_id}


@router.get("/api/runs/{run_id}/replay")
def replay_run(run_id: str, after: int = 0, limit: int = 100):
    run = rt._active().runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return replay_page(run, after=after, limit=limit)


@router.post("/api/runs/diff")
def diff_run(body: dict):
    base_id = body.get("base_run_id", "")
    head_id = body.get("head_run_id", "")
    if base_id == head_id:
        raise HTTPException(status_code=400, detail="base and head runs must be different")
    base = rt._active().runs.get(base_id)
    head = rt._active().runs.get(head_id)
    if base is None or head is None:
        raise HTTPException(status_code=404, detail="base or head run not found")
    base_assets = rt._active().assets.list_assets(run_id=base_id)
    head_assets = rt._active().assets.list_assets(run_id=head_id)
    base_findings = [v for v in rt._active().findings.values() if v.get("run_id") == base_id]
    head_findings = [v for v in rt._active().findings.values() if v.get("run_id") == head_id]
    base_evidence = [v for v in rt._active().evidence.values() if v.get("run_id") == base_id]
    head_evidence = [v for v in rt._active().evidence.values() if v.get("run_id") == head_id]
    return diff_runs(base, head, base_assets, head_assets, base_findings, head_findings, base_evidence, head_evidence)


def _run_state_path(run_id: str):
    return rt._active().root / "sessions" / f"{run_id}.state.json"


def _load_state_or_404(run_id: str):
    if run_id not in rt._active().runs:
        raise HTTPException(status_code=404, detail="run not found")
    path = _run_state_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no workflow state for run")
    return load_run_state(path), path


def _supersede_run_outputs(run_id: str, dependents: set[str]) -> None:
    evidence_ids = set()
    for ev in rt._active().evidence.values():
        if ev.get("run_id") == run_id and ev.get("stage_id") in dependents:
            ev["superseded"] = True
            ev["superseded_by_run_id"] = run_id
            rt._active().save_evidence(ev["id"], ev)
            evidence_ids.add(ev["id"])
    for finding in rt._active().findings.values():
        if finding.get("run_id") == run_id and (set(finding.get("evidence_ids") or []) & evidence_ids):
            finding["superseded"] = True
            finding["superseded_by_run_id"] = run_id
            rt._active().save_finding(finding["id"], finding)


@router.get("/api/runs/{run_id}/workflow-state")
def run_workflow_state(run_id: str):
    state, _ = _load_state_or_404(run_id)
    return {
        "run_id": state.run_id,
        "template_id": state.template_id,
        "target": state.target,
        "current_stage": state.current_stage,
        "stage_status": state.stage_status,
        "checkpoint_version": state.checkpoint_version,
        "budget_status": getattr(state, "budget_status", ""),
        "facts": state.facts,
    }


def _start_resume(run_id: str, state, template: Template) -> dict:
    if rt._get_live(run_id) is not None:
        raise HTTPException(status_code=400, detail="run is already active")
    if not next_ready(template, state):
        raise HTTPException(status_code=400, detail="no pending stages to resume")
    live = rt._LiveRun()
    with rt._live_lock:
        rt._live_runs[run_id] = live
    thread = threading.Thread(
        target=rt._run_in_background,
        args=(run_id, template, state.target, False),
        kwargs={"run_state": state, "session_id": rt._active().runs[run_id].get("session_id", "")},
        daemon=True,
    )
    thread.start()
    return {"run_id": run_id, "status": "started"}


@router.post("/api/runs/{run_id}/control")
def run_control(run_id: str, body: dict):
    action = body.get("action", "")
    if action not in ("skip", "jump", "revisit", "resume"):
        raise HTTPException(status_code=400, detail="action must be skip, jump, revisit, or resume")
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm=true is required for workflow control")
    state, path = _load_state_or_404(run_id)
    template_data = rt._template_store.get(state.template_id)
    if template_data is None:
        raise HTTPException(status_code=404, detail="template not found")
    template = from_dict(Template, template_data)
    try:
        validate_template(template)
    except GraphError as exc:
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc
    if action == "resume":
        return _start_resume(run_id, state, template)

    stage_id = body.get("stage_id", "")
    if stage_id not in {s.id for s in template.stages}:
        raise HTTPException(status_code=404, detail="stage not found")
    with tempfile.TemporaryDirectory() as td:
        log = EventLog(Path(td) / "control.jsonl")
        executor = Executor(template, rt._registry_for(template), log, run_id=run_id, checkpoint_path=path)
        if action == "skip":
            executor.skip_stage(state, stage_id)
        elif action == "jump":
            executor.jump_to(state, stage_id)
        elif action == "revisit":
            dependents = executor.revisit_stage(state, stage_id)
            _supersede_run_outputs(run_id, dependents)
        save_run_state(state, path)
    return {
        "run_id": run_id,
        "action": action,
        "stage_id": stage_id,
        "stage_status": state.stage_status,
        "checkpoint_version": state.checkpoint_version,
    }


@router.post("/api/workflow/apply-suggestion")
def apply_workflow_suggestion(body: dict):
    template_id = body.get("template_id", "")
    suggestion = body.get("suggestion") or {}
    template_data = rt._template_store.get(template_id)
    if template_data is None:
        raise HTTPException(status_code=404, detail="template not found")
    template = from_dict(Template, template_data)
    try:
        updated = apply_suggestion(template, suggestion)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Snapshot with lineage so the evolution loop is traceable in version history.
    new_version = rt._template_store.save_versioned(
        updated.id, to_dict(updated),
        lineage={"source": "selfcheck", "ref_id": str(body.get("ref_id") or "")},
    )
    return {"template_id": updated.id, "new_version": new_version, "stages": [s.id for s in updated.stages]}


@router.post("/api/workflow/review")
def review(body: dict):
    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM 未配置；请在设置里填写 API Key")
    try:
        issues = rt.review_workflow(provider, body.get("template", {}))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"检查失败：{exc}") from exc
    return {"issues": issues}


@router.post("/api/workflow/understand")
def understand(body: dict):
    provider = rt._get_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="LLM 未配置；请在设置里填写 API Key")
    template = body.get("template", {})
    try:
        updated, issues = rt.understand_workflow(provider, template)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"理解失败：{exc}") from exc
    return {"template": updated, "issues": issues}
