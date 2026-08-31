import asyncio
import json
import hashlib
import os
import queue
import secrets
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

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
from lattice_ai.graph import GraphError, validate_template
from lattice_ai.improve import apply_suggestion
from lattice_ai.groups import next_group_id
from lattice_ai.importer import generate_tool_draft
from lattice_ai.github_asset_importer import preview_asset_import
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.llm import OpenAICompatibleProvider, list_models
from lattice_ai.models import Skill, Tool, ToolBinding, Template, from_dict, to_dict
from lattice_ai.preferences import load_preferences, save_preferences
from lattice_ai.persistence import atomic_write_json
from lattice_ai.recipes import load_bundled_recipes, tool_to_yaml, yaml_to_tool
from lattice_ai.report_export import export_report
from lattice_ai.run_diff import diff_runs
from lattice_ai.run_replay import replay_page
from lattice_ai.run_state import load_run_state, next_ready, save_run_state
from lattice_ai.review import generate_findings, generate_report, generate_report_stream, review_workflow, understand_workflow
from lattice_ai.run_context import build_run_context
from lattice_ai.scope import evaluate_scope, is_restricted_target, scope_configured, scope_policy_from_dict
from lattice_ai.selfcheck import evolution_report, group_units, self_check_unit
from lattice_ai.tools import (
    ApprovalDenied,
    ToolError,
    ToolRegistry,
    add_tool_path,
    find_executable,
    tool_available,
    tool_status,
)
from lattice_ai.tool_import import classify_source, detect_mcp, import_tool_source, list_mcp_tools, map_target_to_args, mcp_tools_to_lattice, parse_command
from lattice_ai.workspace import ProjectStore
from lattice_ai import adapters  # noqa: F401  # registers mcp/http_api tool adapters
from lattice_ai import runtime as rt
from lattice_ai.runtime import (  # noqa: F401  # compat: names moved to runtime
    _ANALYSIS_TOOLS,
    _DATA_ROOT,
    _DEFAULTS,
    _DEFAULT_SKILLS,
    _EVIDENCE_TOOLS,
    _LEGACY_RECON_DESCRIPTIONS,
    _LITE_PENTEST_TEMPLATE,
    _LiveRun,
    _MARKETPLACE,
    _MAX_STREAM_DELTA_CHARS,
    _NotifyingEventLog,
    _PROJECTS_ROOT,
    _PROVIDERS,
    _RECON_TOOLS,
    _RunStopped,
    _SETTINGS_FILE,
    _StreamingProvider,
    _TOOLCHAIN_NAMES,
    _VULN_TOOLS,
    _active,
    _append_run_message,
    _backup_legacy_templates,
    _builtin_recon_tool,
    _execute_run,
    _fp_stats,
    _get_live,
    _get_provider,
    _get_provider_for,
    _install_jobs,
    _install_lock,
    _is_legacy_builtin_template,
    _latest_run_id_for_template,
    _live_lock,
    _live_runs,
    _load_settings,
    _manual_registry,
    _migrate_legacy_project_assets,
    _persist_evidence_tools,
    _projects_store,
    _recorded_findings_from_events,
    _registry_for,
    _run_conversation_stream,
    _run_in_background,
    _save_evidence_from_events,
    _seed_global_assets,
    _skill_store,
    _sse_event,
    _store,
    _template_store,
    _tool_store,
    migrate_legacy_session_ids,
)
from lattice_ai.installer import go_bin_dir, install_toolchain
from lattice_ai.generation import generation_done, generation_exists, generation_result, list_generation_events, start_generation


_AUTH_OFF_VALUES = {"1", "true", "yes"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _auth_disabled() -> bool:
    return os.environ.get("LATTICE_AUTH_DISABLED", "").strip().lower() in _AUTH_OFF_VALUES


def _is_loopback_host(host: str) -> bool:
    return (host or "").strip("[]").lower() in _LOOPBACK_HOSTS


def _auth_token() -> str:
    """The remote-access token: LATTICE_TOKEN env wins, otherwise a secret
    generated on first use and persisted under data/auth_token.json."""
    env_token = os.environ.get("LATTICE_TOKEN", "").strip()
    if env_token:
        return env_token
    path = rt._DATA_ROOT / "auth_token.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        token = str(data.get("token", "")).strip()
        if token:
            return token
    except Exception:
        pass
    token = secrets.token_urlsafe(32)
    atomic_write_json(path, {"token": token, "created_at": datetime.now().isoformat(timespec="seconds")})
    return token


@asynccontextmanager
async def _lifespan(app):
    if not _auth_disabled():
        _auth_token()  # generate eagerly so the token file exists from first boot
        # print rather than logging: uvicorn's default config does not surface
        # application loggers, and this notice must be visible to the user
        print(
            "[lattice] remote access requires a token "
            f"(stored in {rt._DATA_ROOT / 'auth_token.json'}, override with LATTICE_TOKEN); "
            "loopback clients are trusted without one",
            flush=True,
        )
    yield


app = FastAPI(title="Lattice AI", version="0.1.0", lifespan=_lifespan)

_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


def _allowed_hostnames() -> set[str]:
    extra = os.environ.get("LATTICE_ALLOWED_HOSTS", "")
    hosts = set(_LOCAL_HOSTNAMES)
    hosts.update(h.strip().lower() for h in extra.split(",") if h.strip())
    return hosts


def _hostname_of(url_or_host: str) -> str:
    value = (url_or_host or "").strip()
    if "://" in value:
        value = urlparse(value).hostname or ""
    else:
        value = value.split("/")[0]
    return value.rsplit("@", 1)[-1].split(":")[0].strip("[]").lower()


@app.middleware("http")
async def _reject_foreign_browser_origins(request, call_next):
    """Block browser-borne cross-site requests (CSRF, DNS rebinding).

    The API is deliberately open to non-browser local clients (scripts,
    tests). Real browser requests always carry Origin/Referer or
    Sec-Fetch-Site headers, and those must point at an allowed host —
    loopback by default, extendable via LATTICE_ALLOWED_HOSTS for LAN use.
    """
    headers = request.headers
    origin = headers.get("origin") or ""
    referer = headers.get("referer") or ""
    fetch_site = headers.get("sec-fetch-site") or ""
    if origin or referer or fetch_site:
        source_host = _hostname_of(origin or referer)
        if source_host:
            ok = source_host in _allowed_hostnames()
        else:
            ok = fetch_site in ("same-origin", "same-site", "none")
        if not ok:
            return Response(
                content='{"detail":"request origin is not allowed"}',
                status_code=403,
                media_type="application/json",
            )
    return await call_next(request)


@app.middleware("http")
async def _require_token_for_remote_peers(request, call_next):
    """Token auth for non-loopback peers.

    Loopback clients (the local UI, the vite dev proxy, local scripts) are
    trusted without a token. When the server is bound beyond localhost,
    remote peers must present the token via ``Authorization: Bearer`` or
    ``X-Lattice-Token``; ``LATTICE_AUTH_DISABLED=1`` opts out explicitly.
    """
    if _auth_disabled():
        return await call_next(request)
    client_host = request.client.host if request.client else ""
    if _is_loopback_host(client_host):
        return await call_next(request)
    provided = request.headers.get("x-lattice-token", "").strip()
    authorization = request.headers.get("authorization", "")
    if not provided and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided or not secrets.compare_digest(provided, _auth_token()):
        return Response(
            content='{"detail":"authorization required for remote access"}',
            status_code=401,
            media_type="application/json",
        )
    return await call_next(request)

@app.get("/health")
def health():
    return {"status": "ok"}

# ---- route modules ----
from importlib import import_module as _import_module

from lattice_ai.routes.projects import router as projects_router
from lattice_ai.routes.templates import router as templates_router
from lattice_ai.routes.tools import router as tools_router
from lattice_ai.routes.runs import router as runs_router
from lattice_ai.routes.conversations import router as conversations_router
from lattice_ai.routes.marketplace import router as marketplace_router
from lattice_ai.routes.trash import router as trash_router
from lattice_ai.routes.approvals import router as approvals_router
from lattice_ai.routes.settings import router as settings_router
from lattice_ai.routes.skills import router as skills_router
from lattice_ai.routes.assets import router as assets_router
from lattice_ai.routes.dashboard import router as dashboard_router
from lattice_ai.routes.executions import router as executions_router
# module name "import" is a keyword, so a plain import statement can't reach it
import_router = _import_module("lattice_ai.routes.import").router

app.include_router(projects_router)
app.include_router(templates_router)
app.include_router(tools_router)
app.include_router(runs_router)
app.include_router(conversations_router)
app.include_router(marketplace_router)
app.include_router(trash_router)
app.include_router(approvals_router)
app.include_router(settings_router)
app.include_router(skills_router)
app.include_router(assets_router)
app.include_router(dashboard_router)
app.include_router(executions_router)
app.include_router(import_router)


# Serve the built web UI from the same origin when it exists. Registered
# last so API routes keep precedence; hash routing means no SPA fallback
# rewrite is needed. Development still uses the vite dev server.
# Precedence: package-shipped web_dist (pip install) → repo web/dist (source).
from fastapi.staticfiles import StaticFiles  # noqa: E402

_WEB_PACKAGED = Path(__file__).resolve().parent / "web_dist"
_WEB_REPO = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
_WEB_DIST = _WEB_PACKAGED if _WEB_PACKAGED.is_dir() else _WEB_REPO
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")
