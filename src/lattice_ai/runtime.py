"""Shared runtime state and services for the Lattice AI server.

Everything mutable that routes operate on lives here: project/template/
tool/skill stores, provider construction, tool registries with the active
security context, the live-run registry, and the run/conversation
execution machinery. Route modules access these as ``rt.<name>`` so tests
can monkeypatch a single module.
"""

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
from lattice_ai.generation import generation_done, generation_exists, generation_result, list_generation_events, start_generation
from lattice_ai.installer import go_bin_dir, install_toolchain
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
    find_real_executable,
)
from lattice_ai.tool_import import classify_source, detect_mcp, import_tool_source, list_mcp_tools, map_target_to_args, mcp_tools_to_lattice, parse_command
from lattice_ai.workspace import ProjectStore


# ------------------------------------------------------------------
# moved verbatim from server.py
# ------------------------------------------------------------------

_RECON_TOOLS = [
    {"name": "dnsx", "description": "内置轻量近似：DNS 记录解析（不等于真实 dnsx）", "runner": "builtin"},
    {"name": "httpx", "description": "内置轻量近似：HTTP 存活探测", "runner": "builtin"},
    {"name": "subfinder", "description": "内置轻量近似：crt.sh 被动子域枚举", "runner": "builtin"},
    {"name": "naabu", "description": "内置轻量近似：常见端口 TCP 探测", "runner": "builtin"},
    {"name": "nmap", "description": "内置轻量近似：常见端口扫描（不等于真实 nmap）", "runner": "builtin"},
    {"name": "whatweb", "description": "内置轻量近似：响应头/页面技术特征识别", "runner": "builtin"},
    {"name": "ffuf", "description": "内置轻量近似：固定路径探测（不等于真实 ffuf）", "runner": "builtin"},
    {"name": "katana", "description": "内置轻量近似：抓取首页链接", "runner": "builtin"},
]

_VULN_TOOLS = [
    {"name": "nuclei", "description": "Run nuclei vulnerability scanner", "runner": "cli",
     "command": ["nuclei", "-u", "{target}"], "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}},
    {"name": "sqlmap", "description": "Test and exploit SQL injection", "runner": "cli",
     "command": ["sqlmap", "-u", "{target}", "--batch"], "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}},
    {"name": "dalfox", "description": "Detect and verify XSS", "runner": "cli",
     "command": ["dalfox", "url", "{target}"], "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}},
]

_TOOLCHAIN_NAMES = ["nuclei", "sqlmap", "dalfox", "httpx", "subfinder", "naabu", "katana", "whatweb"]

_ANALYSIS_TOOLS = [
    {"name": "js_extract", "description": "内置 JS 端点/参数提取", "runner": "builtin"},
    {"name": "fingerprint_cve", "description": "内置依赖版本→CVE 匹配", "runner": "builtin"},
    {"name": "jwt_analyze", "description": "内置 JWT 攻击检测", "runner": "builtin"},
    {"name": "crypto_analyze", "description": "内置加密弱项/密钥提取", "runner": "builtin"},
    {"name": "value_fuzz", "description": "内置值池联动 fuzz", "runner": "builtin"},
]

_EVIDENCE_TOOLS = [
    {"name": "record_finding", "description": "记录结构化发现", "runner": "builtin"},
    {"name": "record_loot", "description": "记录战利品数据", "runner": "builtin"},
    {"name": "record_host", "description": "记录主机/资产", "runner": "builtin"},
]

_LITE_PENTEST_TEMPLATE = {
    "id": "builtin-full-pentest-lite",
    "name": "全流程渗透测试（轻量版）",
    "name_i18n": {"zh": "全流程渗透测试（轻量版）", "en": "Full Pentest Pipeline (Lite)"},
    "summary": "内置侦查 + AI 风险研判，零外部依赖，开箱可用。",
    "description_i18n": {"zh": "内置侦查 + AI 风险研判，零外部依赖，开箱可用。",
                         "en": "Builtin recon + AI risk triage, zero external dependencies, works out of the box."},
    "start": "normalize",
    "stages": [
        {"id": "normalize", "name": "目标规范化", "goal": "确认目标格式和 scope", "depends_on": [], "skills": [{"skill": "recon-playbook"}]},
        {"id": "liveness", "name": "存活发现", "goal": "判断目标是否可达", "depends_on": ["normalize"], "tools": [{"tool": "dnsx", "key": "dnsx-live"}, {"tool": "httpx", "key": "httpx-live"}], "skills": [{"skill": "recon-playbook"}, {"skill": "evidence-collection"}]},
        {"id": "subdomain", "name": "子域与资产发现", "goal": "扩大攻击面", "depends_on": ["liveness"], "tools": [{"tool": "subfinder", "key": "subfinder"}], "gates": [{"name": "has_subdomains", "check": {"op": "truthy", "key": "subfinder.subdomains"}, "on_fail": "warn"}], "skills": [{"skill": "recon-playbook"}, {"skill": "evidence-collection"}]},
        {"id": "ports", "name": "端口与服务", "goal": "识别端口、服务、版本", "depends_on": ["subdomain"], "tools": [{"tool": "naabu", "key": "naabu"}, {"tool": "nmap", "key": "nmap"}], "skills": [{"skill": "recon-playbook"}, {"skill": "evidence-collection"}]},
        {"id": "web_fingerprint", "name": "Web 指纹与端点", "goal": "识别技术栈、目录、端点", "depends_on": ["ports"], "tools": [{"tool": "whatweb", "key": "whatweb"}, {"tool": "ffuf", "key": "ffuf"}, {"tool": "katana", "key": "katana"}], "skills": [{"skill": "web-enumeration"}, {"skill": "evidence-collection"}]},
        {"id": "js_collect", "name": "JS 收集", "goal": "抓取页面引用的 JS 资源", "depends_on": ["web_fingerprint"], "tools": [{"tool": "katana", "key": "katana-js"}], "skills": [{"skill": "web-enumeration"}]},
        {"id": "js_analyze", "name": "JS 深度分析", "goal": "提取端点、参数、密钥线索", "depends_on": ["js_collect"], "tools": [{"tool": "js_extract", "key": "js_extract"}], "gates": [{"name": "has_endpoints", "check": {"op": "truthy", "key": "js_extract.endpoints"}, "on_fail": "block"}], "skills": [{"skill": "web-enumeration"}, {"skill": "finding-format"}]},
        {"id": "dep_cve", "name": "依赖版本 CVE 匹配", "goal": "从指纹/JS 提取版本并匹配 CVE", "depends_on": ["js_analyze"], "tools": [{"tool": "fingerprint_cve", "key": "fingerprint_cve"}, {"tool": "record_finding", "key": "record_cve", "defaults": {"title": "依赖版本存在已知 CVE", "severity": "high", "status": "confirmed", "cwe": "CWE-1395"}}], "skills": [{"skill": "finding-format"}, {"skill": "evidence-collection"}]},
        {"id": "triage", "name": "风险研判", "goal": "把证据归纳为潜在风险点", "depends_on": ["dep_cve"], "skills": [{"skill": "claim-grounding"}, {"skill": "evidence-collection"}]},
        {"id": "report", "name": "报告产出", "goal": "生成交付报告", "depends_on": ["triage"], "skills": [{"skill": "report-format"}]},
    ],
    "tools": _RECON_TOOLS + _ANALYSIS_TOOLS + _EVIDENCE_TOOLS,
    "skills": [],
}

_WEB_FULL_TEMPLATE = {'id': 'builtin-web-full',
     'name': 'Web 完整渗透（18 阶段 DAG）',
     'name_i18n': {'zh': 'Web 完整渗透（18 阶段 DAG）', 'en': 'Web Full Pentest (18-Stage DAG)'},
     'summary': '侦察→JS 分析→并行漏洞分支→验证→定级→报告的大 DAG。',
     'description_i18n': {'zh': '侦察→JS 分析→并行漏洞分支→验证→定级→报告的大 DAG。',
                          'en': 'Large DAG: recon → JS analysis → parallel vuln branches → verification → triage → report.'},
     'start': 'normalize',
     'stages': [{'id': 'normalize',
                 'name': '目标规范化',
                 'goal': '确认目标格式和 scope',
                 'depends_on': [],
                 'skills': [{'skill': 'recon-playbook'}]},
                {'id': 'liveness',
                 'name': '存活发现',
                 'goal': '判断目标是否可达',
                 'depends_on': ['normalize'],
                 'tools': [{'tool': 'dnsx', 'key': 'dnsx-live'}, {'tool': 'httpx', 'key': 'httpx-live'}],
                 'skills': [{'skill': 'recon-playbook'}, {'skill': 'evidence-collection'}]},
                {'id': 'subdomain',
                 'name': '子域与资产发现',
                 'goal': '扩大攻击面',
                 'depends_on': ['liveness'],
                 'tools': [{'tool': 'subfinder', 'key': 'subfinder'}],
                 'gates': [{'name': 'has_subdomains',
                            'check': {'op': 'truthy', 'key': 'subfinder.subdomains'},
                            'on_fail': 'warn'}],
                 'skills': [{'skill': 'recon-playbook'}, {'skill': 'evidence-collection'}]},
                {'id': 'ports',
                 'name': '端口与服务',
                 'goal': '识别端口、服务、版本',
                 'depends_on': ['subdomain'],
                 'tools': [{'tool': 'naabu', 'key': 'naabu'}, {'tool': 'nmap', 'key': 'nmap'}],
                 'skills': [{'skill': 'recon-playbook'}, {'skill': 'evidence-collection'}]},
                {'id': 'web_fingerprint',
                 'name': 'Web 指纹与端点',
                 'goal': '识别技术栈、目录、端点',
                 'depends_on': ['ports'],
                 'tools': [{'tool': 'whatweb', 'key': 'whatweb'},
                           {'tool': 'ffuf', 'key': 'ffuf'},
                           {'tool': 'katana', 'key': 'katana'}],
                 'skills': [{'skill': 'web-enumeration'}, {'skill': 'evidence-collection'}]},
                {'id': 'js_collect',
                 'name': 'JS 收集',
                 'goal': '抓取页面引用的 JS 资源',
                 'depends_on': ['web_fingerprint'],
                 'tools': [{'tool': 'katana', 'key': 'katana-js'}],
                 'skills': [{'skill': 'web-enumeration'}]},
                {'id': 'js_analyze',
                 'name': 'JS 深度分析',
                 'goal': '提取端点、参数、密钥线索',
                 'depends_on': ['js_collect'],
                 'tools': [{'tool': 'js_extract', 'key': 'js_extract'}],
                 'gates': [{'name': 'has_endpoints',
                            'check': {'op': 'truthy', 'key': 'js_extract.endpoints'},
                            'on_fail': 'block'}],
                 'skills': [{'skill': 'web-enumeration'}, {'skill': 'finding-format'}]},
                {'id': 'dep_cve',
                 'name': '依赖版本 CVE 匹配',
                 'goal': '从指纹/JS 提取版本并匹配 CVE',
                 'depends_on': ['js_analyze'],
                 'tools': [{'tool': 'fingerprint_cve', 'key': 'fingerprint_cve'},
                           {'tool': 'record_finding',
                            'key': 'record_cve',
                            'defaults': {'title': '依赖版本存在已知 CVE',
                                         'severity': 'high',
                                         'status': 'confirmed',
                                         'cwe': 'CWE-1395'}}],
                 'skills': [{'skill': 'finding-format'}, {'skill': 'evidence-collection'}]},
                {'id': 'osint',
                 'name': '源码泄露/被动 OSINT',
                 'goal': '查找公开泄露与敏感信息',
                 'depends_on': ['normalize'],
                 'optional': True,
                 'skills': [{'skill': 'recon-playbook'}]},
                {'id': 'api_fuzz',
                 'name': 'API 参数模糊与越权',
                 'goal': '值池联动探测越权/未授权',
                 'depends_on': ['js_analyze'],
                 'condition': {'op': 'truthy', 'key': 'js_extract.endpoints'},
                 'tools': [{'tool': 'value_fuzz',
                            'key': 'value_fuzz',
                            'args_from': {'endpoints': 'js_extract.endpoints'}},
                           {'tool': 'record_finding',
                            'key': 'record_api',
                            'defaults': {'title': '越权/未授权访问',
                                         'severity': 'high',
                                         'status': 'confirmed',
                                         'cwe': 'CWE-639'}}],
                 'skills': [{'skill': 'finding-format'}, {'skill': 'evidence-collection'}]},
                {'id': 'auth_attack',
                 'name': 'JWT/认证攻击',
                 'goal': '检测 JWT 与认证弱点',
                 'depends_on': ['js_analyze'],
                 'condition': {'op': 'truthy', 'key': 'js_extract.secrets'},
                 'tools': [{'tool': 'jwt_analyze', 'key': 'jwt_analyze'},
                           {'tool': 'record_finding',
                            'key': 'record_auth',
                            'defaults': {'title': 'JWT 认证弱点',
                                         'severity': 'high',
                                         'status': 'confirmed',
                                         'cwe': 'CWE-345'}}],
                 'skills': [{'skill': 'finding-format'}, {'skill': 'evidence-collection'}]},
                {'id': 'crypto_attack',
                 'name': '加密弱项分析',
                 'goal': '提取密钥与加密弱项',
                 'depends_on': ['js_analyze'],
                 'condition': {'op': 'truthy', 'key': 'js_extract.secrets'},
                 'tools': [{'tool': 'crypto_analyze',
                            'key': 'crypto_analyze',
                            'args_from': {'text': 'js_extract.secrets'}},
                           {'tool': 'record_finding',
                            'key': 'record_crypto',
                            'defaults': {'title': '加密密钥泄露',
                                         'severity': 'high',
                                         'status': 'confirmed',
                                         'cwe': 'CWE-321'}}],
                 'skills': [{'skill': 'finding-format'}, {'skill': 'evidence-collection'}]},
                {'id': 'injection',
                 'name': '注入类漏洞',
                 'goal': 'SQLi/XSS/SSTI/SSRF/XXE/命令注入等测试',
                 'depends_on': ['web_fingerprint'],
                 'tools': [{'tool': 'nuclei', 'key': 'nuclei'},
                           {'tool': 'sqlmap', 'key': 'sqlmap'},
                           {'tool': 'dalfox', 'key': 'dalfox'},
                           {'tool': 'record_finding',
                            'key': 'record_injection',
                            'defaults': {'title': '注入类漏洞',
                                         'severity': 'high',
                                         'status': 'confirmed',
                                         'cwe': 'CWE-89'}}],
                 'skills': [{'skill': 'finding-format'}, {'skill': 'evidence-collection'}]},
                {'id': 'bypass_403',
                 'name': '401/403 绕过',
                 'goal': '测试认证绕过与访问控制',
                 'depends_on': ['web_fingerprint'],
                 'condition': {'op': 'truthy', 'key': 'ffuf.blocked'},
                 'skills': [{'skill': 'web-enumeration'}, {'skill': 'finding-format'}]},
                {'id': 'high_risk',
                 'name': '高危探测',
                 'goal': 'RCE/反序列化等高危验证',
                 'depends_on': ['api_fuzz', 'injection'],
                 'condition': {'op': 'or',
                               'conditions': [{'op': 'truthy', 'key': 'value_fuzz.probes'},
                                              {'op': 'truthy', 'key': 'nuclei.findings'},
                                              {'op': 'truthy', 'key': 'sqlmap.findings'},
                                              {'op': 'truthy', 'key': 'dalfox.findings'}]},
                 'skills': [{'skill': 'finding-format'}, {'skill': 'evidence-collection'}]},
                {'id': 'verify',
                 'name': '验证复测',
                 'goal': '证明漏洞真实存在并固证',
                 'depends_on': ['api_fuzz',
                                'auth_attack',
                                'crypto_attack',
                                'injection',
                                'bypass_403',
                                'high_risk'],
                 'tools': [{'tool': 'record_finding',
                            'key': 'record_verify',
                            'defaults': {'title': '漏洞验证', 'severity': 'medium', 'status': 'confirmed'}},
                           {'tool': 'record_loot', 'key': 'record_loot'}],
                 'gates': [{'name': 'evidence_complete',
                            'check': {'op': 'truthy', 'key': 'record_verify.recorded'},
                            'on_fail': 'block'}],
                 'skills': [{'skill': 'verification'}, {'skill': 'evidence-collection'}]},
                {'id': 'triage',
                 'name': '去重与定级',
                 'goal': '去重、CWE/CVSS、证据关联',
                 'depends_on': ['verify'],
                 'gates': [{'name': 'findings_with_evidence',
                            'check': {'op': 'truthy', 'key': 'record_loot.recorded'},
                            'on_fail': 'block'}],
                 'skills': [{'skill': 'claim-grounding'}, {'skill': 'evidence-collection'}]},
                {'id': 'report',
                 'name': '报告产出',
                 'goal': '生成交付报告',
                 'depends_on': ['triage'],
                 'skills': [{'skill': 'report-format'}]}],
     'tools': [{'name': 'dnsx', 'description': '内置轻量近似：DNS 记录解析（不等于真实 dnsx）', 'runner': 'builtin'},
               {'name': 'httpx', 'description': '内置轻量近似：HTTP 存活探测', 'runner': 'builtin'},
               {'name': 'subfinder', 'description': '内置轻量近似：crt.sh 被动子域枚举', 'runner': 'builtin'},
               {'name': 'naabu', 'description': '内置轻量近似：常见端口 TCP 探测', 'runner': 'builtin'},
               {'name': 'nmap', 'description': '内置轻量近似：常见端口扫描（不等于真实 nmap）', 'runner': 'builtin'},
               {'name': 'whatweb', 'description': '内置轻量近似：响应头/页面技术特征识别', 'runner': 'builtin'},
               {'name': 'ffuf', 'description': '内置轻量近似：固定路径探测（不等于真实 ffuf）', 'runner': 'builtin'},
               {'name': 'katana', 'description': '内置轻量近似：抓取首页链接', 'runner': 'builtin'},
               {'name': 'js_extract', 'description': '内置 JS 端点/参数提取', 'runner': 'builtin'},
               {'name': 'fingerprint_cve', 'description': '内置依赖版本→CVE 匹配', 'runner': 'builtin'},
               {'name': 'jwt_analyze', 'description': '内置 JWT 攻击检测', 'runner': 'builtin'},
               {'name': 'crypto_analyze', 'description': '内置加密弱项/密钥提取', 'runner': 'builtin'},
               {'name': 'value_fuzz', 'description': '内置值池联动 fuzz', 'runner': 'builtin'},
               {'name': 'nuclei',
                'description': 'Run nuclei vulnerability scanner',
                'runner': 'cli',
                'command': ['nuclei', '-u', '{target}'],
                'parameters': {'type': 'object',
                               'properties': {'target': {'type': 'string'}},
                               'required': ['target']}},
               {'name': 'sqlmap',
                'description': 'Test and exploit SQL injection',
                'runner': 'cli',
                'command': ['sqlmap', '-u', '{target}', '--batch'],
                'parameters': {'type': 'object',
                               'properties': {'target': {'type': 'string'}},
                               'required': ['target']}},
               {'name': 'dalfox',
                'description': 'Detect and verify XSS',
                'runner': 'cli',
                'command': ['dalfox', 'url', '{target}'],
                'parameters': {'type': 'object',
                               'properties': {'target': {'type': 'string'}},
                               'required': ['target']}},
               {'name': 'record_finding', 'description': '记录结构化发现', 'runner': 'builtin'},
               {'name': 'record_loot', 'description': '记录战利品数据', 'runner': 'builtin'},
               {'name': 'record_host', 'description': '记录主机/资产', 'runner': 'builtin'}],
     'skills': []}

_MARKETPLACE = {
    "builtin-web-full": {
        "id": "builtin-web-full",
        "name": "Web 完整渗透（18 阶段 DAG）",
        "name_i18n": _WEB_FULL_TEMPLATE["name_i18n"],
        "description": "侦察→JS 分析→并行漏洞分支→验证→定级→报告的大 DAG；nuclei/sqlmap/dalfox 缺失时自动回退内置轻量近似。",
        "description_i18n": {
            "zh": "侦察→JS 分析→并行漏洞分支→验证→定级→报告的大 DAG；nuclei/sqlmap/dalfox 缺失时自动回退内置轻量近似。",
            "en": "Large DAG: recon → JS analysis → parallel vuln branches → verification → triage → report. Falls back to builtin lightweight sims when nuclei/sqlmap/dalfox are missing.",
        },
        "requires_tools": ["nuclei", "sqlmap", "dalfox"],
        "template": _WEB_FULL_TEMPLATE,
    },
    "builtin-full-pentest-lite": {
        "id": "builtin-full-pentest-lite",
        "name": "全流程渗透测试（轻量版）",
        "name_i18n": _LITE_PENTEST_TEMPLATE["name_i18n"],
        "description": "内置侦查 + AI 风险研判，零外部依赖，开箱可用",
        "description_i18n": {
            "zh": "内置侦查 + AI 风险研判，零外部依赖，开箱可用",
            "en": "Builtin recon + AI risk triage, zero external dependencies, works out of the box.",
        },
        "requires_tools": [],
        "template": _LITE_PENTEST_TEMPLATE,
    },
}

# Every builtin template is marketplace-installable: the 10-template matrix
# ships the same dicts that get seeded into the library, so the marketplace
# panel and the library always offer the same set.
from lattice_ai.builtin_templates import MATRIX_TEMPLATES  # noqa: E402

for _matrix in MATRIX_TEMPLATES:
    _MARKETPLACE[_matrix["id"]] = {
        "id": _matrix["id"],
        "name": _matrix["name"],
        "name_i18n": _matrix.get("name_i18n"),
        "description": _matrix.get("summary", ""),
        "description_i18n": _matrix.get(
            "description_i18n",
            {"zh": _matrix.get("summary", ""), "en": _matrix.get("summary", "")},
        ),
        "requires_tools": [],
        "template": _matrix,
    }
del _matrix

_DEFAULTS = {
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-5.1",
    "api_key": "",
    "reasoning_effort": "",
}

from lattice_ai.paths import data_root  # noqa: E402

_SETTINGS_FILE = data_root() / "settings.json"

_DATA_ROOT = _SETTINGS_FILE.parent
_template_store = TemplateStore(_DATA_ROOT / "templates")
_tool_store = ToolStore(_DATA_ROOT / "tools")
_skill_store = SkillStore(_DATA_ROOT / "skills")


def _migrate_legacy_project_assets():
    projects_root = _SETTINGS_FILE.parent / "projects"
    if not projects_root.exists():
        return
    for project_dir in projects_root.iterdir():
        if not project_dir.is_dir():
            continue
        for p in (project_dir / "templates").glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                _template_store.save(data["id"], data)
                p.unlink(missing_ok=True)
            except Exception:
                continue
        for p in (project_dir / "tools").glob("*.yaml"):
            try:
                tool = yaml_to_tool(p.read_text(encoding="utf-8"))
                _tool_store.save(tool.name, to_dict(tool))
                p.unlink(missing_ok=True)
            except Exception:
                continue
        for p in (project_dir / "skills").glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                _skill_store.save(data["name"], data)
                p.unlink(missing_ok=True)
            except Exception:
                continue
        for sub in ("templates", "tools", "skills"):
            d = project_dir / sub
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass


def _load_settings():
    settings = dict(_DEFAULTS)
    for key, env in (("base_url", "LATTICE_BASE_URL"), ("model", "LATTICE_MODEL"), ("api_key", "LATTICE_API_KEY")):
        val = os.environ.get(env)
        if val:
            settings[key] = val
    if _SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(_SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return settings


_PROVIDERS = {
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-5.1", "reasoning": {"efforts": ["off", "low", "medium", "high"]}},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-pro", "reasoning": {"efforts": ["off", "low", "high", "max"], "thinking": True}},
}

_DEFAULT_SKILLS: dict[str, dict] = {
    "recon-basics": {
        "name": "recon-basics",
        "description": "Basic reconnaissance methodology",
        "category": "recon",
        "tags": ["recon", "enumeration"],
        "content": "# Recon Basics\n1. Enumerate subdomains\n2. Identify live hosts",
    },
    "recon-playbook": {
        "name": "recon-playbook",
        "description": "Recon methodology and escalation gates",
        "category": "recon",
        "tags": ["recon", "methodology"],
        "content": "# Recon Playbook\n1. Normalize target and scope.\n2. Check liveness.\n3. Discover subdomains and assets.\n4. Enumerate ports and services.\n5. Identify web tech and endpoints.\n6. Record evidence for every step.\nIf a step has no result, continue to the next step.",
    },
    "web-enumeration": {
        "name": "web-enumeration",
        "description": "Web paths, fingerprinting and endpoint discovery",
        "category": "web",
        "tags": ["web", "enumeration"],
        "content": "# Web Enumeration\n1. Fingerprint tech stack.\n2. Discover directories and files.\n3. Crawl endpoints.\n4. Record HTTP responses as evidence.",
    },
    "evidence-collection": {
        "name": "evidence-collection",
        "description": "Record reproducible evidence for every tool execution",
        "category": "reporting",
        "tags": ["evidence", "audit"],
        "content": "# Evidence Collection\nFor every tool execution record:\n- command and args\n- output\n- timestamp\n- exit code\nNever claim a finding without evidence.",
    },
    "finding-format": {
        "name": "finding-format",
        "description": "Structured finding format",
        "category": "reporting",
        "tags": ["finding", "report"],
        "content": "# Finding Format\nEach finding must include title, severity, status, cwe, target, confidence, evidence_ids, summary, impact, remediation.",
    },
    "claim-grounding": {
        "name": "claim-grounding",
        "description": "Every claim must be grounded in evidence",
        "category": "reporting",
        "tags": ["anti-hallucination", "evidence"],
        "content": "# Claim Grounding\nEvery claim must cite an evidence id. Do not infer ports, versions, or vulnerabilities that are not present in evidence.",
    },
    "verification": {
        "name": "verification",
        "description": "Re-test candidate findings before reporting",
        "category": "validation",
        "tags": ["verification", "validation"],
        "content": "# Verification\nRe-run the proof for each candidate finding. Only confirmed findings may enter the report.",
    },
    "report-format": {
        "name": "report-format",
        "description": "Markdown report structure",
        "category": "reporting",
        "tags": ["report", "markdown"],
        "content": "# Report Format\nUse sections: Executive Summary, Scope, Findings, Evidence Appendix, Remediation.",
    },
    "api-auth-testing": {
        "name": "api-auth-testing",
        "description": "API authentication and authorization testing methodology",
        "category": "api",
        "tags": ["api", "auth"],
        "content": "# API Auth Testing\n1. Discover API documentation endpoints (swagger/openapi/api-docs).\n2. Test token handling: alg=none, kid injection, weak signing secrets.\n3. Probe object-level authorization (IDOR) by varying endpoint identifiers.\n4. Record evidence for every probe; never claim auth bypass without a response diff.",
    },
}

_PROJECTS_ROOT = _SETTINGS_FILE.parent / "projects"

_store = None


_LEGACY_RECON_DESCRIPTIONS = {
    "Resolve DNS records",
    "Probe HTTP endpoints",
    "Passive subdomain discovery",
    "Fast port discovery",
    "Port scan with nmap",
    "Identify web technologies",
    "Directory and parameter fuzzing",
    "Crawl and discover endpoints",
}


def _builtin_recon_tool(name: str, description: str) -> dict:
    return {
        "name": name,
        "description": description,
        "runner": "builtin",
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
        "output": {},
        "command": [],
        "scope": [],
        "approval": "allow",
        "secret_fields": [],
    }


def _is_legacy_builtin_template(data: dict) -> bool:
    if "transitions" in data:
        return True
    return any(t.get("description") in _LEGACY_RECON_DESCRIPTIONS for t in data.get("tools", []))


def _backup_legacy_templates() -> None:
    """Copy pre-DAG builtin templates (those still carrying transitions) to .backup/."""
    backup_dir = _template_store.root / ".backup"
    for template_id, template in (
        (_LITE_PENTEST_TEMPLATE["id"], _LITE_PENTEST_TEMPLATE),
    ):
        existing = _template_store.get(template_id)
        if existing and "transitions" in existing:
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"{template_id}.json").write_text(
                json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def _seed_global_assets():
    _backup_legacy_templates()
    trashed_templates = {item["name"] for item in _template_store.trash_list()}
    trashed_tools = {item["name"] for item in _tool_store.trash_list()}
    trashed_skills = {item["name"] for item in _skill_store.trash_list()}

    for template_id, template in (
        (_LITE_PENTEST_TEMPLATE["id"], _LITE_PENTEST_TEMPLATE),
        (_WEB_FULL_TEMPLATE["id"], _WEB_FULL_TEMPLATE),
    ):
        if template_id in trashed_templates:
            continue
        existing = _template_store.get(template_id)
        stale = existing is not None and (
            "name_i18n" not in existing or "description_i18n" not in existing
        )
        if existing is None or _is_legacy_builtin_template(existing) or stale:
            _template_store.save(template_id, template)
    from lattice_ai.builtin_templates import seed_matrix_templates

    seed_matrix_templates(_template_store)
    skill_names = {s["name"] for s in _skill_store.list()}
    for name, data in _DEFAULT_SKILLS.items():
        if name not in skill_names and name not in trashed_skills:
            _skill_store.save(name, data)
    existing_tools = {t["name"]: t for t in _tool_store.list()}
    for tool in _RECON_TOOLS:
        if tool["name"] in trashed_tools:
            continue
        existing = existing_tools.get(tool["name"])
        if existing is None or existing.get("description") in _LEGACY_RECON_DESCRIPTIONS:
            _tool_store.save(tool["name"], _builtin_recon_tool(tool["name"], tool["description"]))
    tool_names = set(existing_tools)
    for recipe in load_bundled_recipes():
        if recipe.name not in tool_names and recipe.name not in trashed_tools:
            _tool_store.save(recipe.name, to_dict(recipe))


def _projects_store() -> ProjectStore:
    global _store
    if _store is None:
        add_tool_path(go_bin_dir())
        _migrate_legacy_project_assets()
        _seed_global_assets()
        _store = ProjectStore(_PROJECTS_ROOT, seed_settings=_load_settings())
        for project in _store._projects.values():
            migrate_legacy_session_ids(project)
    return _store


def migrate_legacy_session_ids(project) -> bool:
    """Idempotently backfill session_id on legacy run/finding/evidence/asset records.

    Records without a session_id are assigned to a stable default task conversation
    created on first run (marked ``is_default`` so repeated migrations never create
    another one). Returns True when any record was changed.
    """
    unbound_runs = [r for r in project.runs.values() if not r.get("session_id")]
    unbound_findings = [f for f in project.findings.values() if not f.get("session_id")]
    unbound_evidence = [e for e in project.evidence.values() if not e.get("session_id")]
    unbound_assets = [a for a in project.assets._assets if not a.get("session_id")]
    if not (unbound_runs or unbound_findings or unbound_evidence or unbound_assets):
        return False

    default_id = None
    for conv in project.conversations:
        if conv.get("kind") == "task" and conv.get("is_default"):
            default_id = conv["id"]
            break
    if default_id is None:
        conv = {
            "id": f"conv_default_{project.id}",
            "name": "默认会话",
            "kind": "task",
            "template_id": "",
            "model": "",
            "reasoning_effort": "",
            "project_id": project.id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "messages": [],
            "target": "",
            "autonomous": False,
            "self_check": False,
            "last_run_id": "",
            "is_default": True,
        }
        project.upsert_conversation(conv)
        default_id = conv["id"]

    changed = False
    for run_id, run in project.runs.items():
        if not run.get("session_id"):
            run["session_id"] = default_id
            project.save_run(run_id, run)
            changed = True
    for finding in project.findings.values():
        if not finding.get("session_id"):
            finding["session_id"] = default_id
            project.save_finding(finding["id"], finding)
            changed = True
    for evidence in project.evidence.values():
        if not evidence.get("session_id"):
            evidence["session_id"] = default_id
            project.save_evidence(evidence["id"], evidence)
            changed = True
    assets_changed = False
    for asset in project.assets._assets:
        if not asset.get("session_id"):
            asset["session_id"] = default_id
            assets_changed = True
    if assets_changed:
        project.assets._save()
        changed = True
    return changed


def _active():
    return _projects_store().active()


def _latest_run_id_for_template(template_id: str) -> str:
    candidates = [r for r in _active().runs.values() if r.get("template_id") == template_id]
    if not candidates:
        return ""
    return max(candidates, key=lambda r: r.get("created_at", ""))["id"]


def _save_evidence_from_events(project, run_id, events, session_id=""):
    for event in events:
        if event.get("type") != "tool_result":
            continue
        data = event.get("data") or {}
        evidence_id = f"evt_{run_id[:8]}_{event.get('seq')}"
        payload = {
            "id": evidence_id,
            "run_id": run_id,
            "stage_id": data.get("stage", ""),
            "tool": data.get("tool", ""),
            "session_id": session_id,
            "result": data.get("result") or {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "hash": hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
        }
        project.save_evidence(evidence_id, payload)


def _persist_evidence_tools(project, run_id, session_id, events):
    """Persist record_finding / record_loot / record_host tool results from a run.

    These evidence builtins are pure functions; the run layer collects their
    tool_result events here so findings/loot/assets actually reach the stores.
    """
    loot = []
    for event in events:
        if event.get("type") != "tool_result":
            continue
        data = event.get("data") or {}
        tool = data.get("tool")
        result = data.get("result") or {}
        if tool == "record_finding":
            finding = result.get("finding")
            if isinstance(finding, dict) and finding.get("title"):
                finding = dict(finding)
                finding["id"] = f"f_{run_id[:8]}_{uuid.uuid4().hex[:6]}"
                finding["run_id"] = run_id
                finding["session_id"] = session_id
                project.save_finding(finding["id"], finding)
        elif tool == "record_loot":
            loot_data = result.get("loot")
            if isinstance(loot_data, dict) and loot_data:
                loot.append(loot_data)
        elif tool == "record_host":
            asset = result.get("asset")
            if isinstance(asset, dict) and asset.get("value"):
                kind = str(asset.get("kind") or "domain")
                if kind == "host":
                    kind = "domain"  # AssetStore has no 'host' kind
                try:
                    project.assets.upsert_asset(
                        kind=kind,
                        value=asset["value"],
                        source_run_id=run_id,
                        source_tool="record_host",
                        session_id=session_id,
                    )
                except ValueError:
                    continue
    if loot:
        run = project.runs.get(run_id)
        if run is not None:
            run["loot"] = list(run.get("loot") or []) + loot
            project.save_run(run_id, run)


def _recorded_findings_from_events(events):
    """Collect finding dicts recorded via record_finding during a run."""
    findings = []
    for event in events:
        if event.get("type") != "tool_result":
            continue
        data = event.get("data") or {}
        if data.get("tool") != "record_finding":
            continue
        finding = (data.get("result") or {}).get("finding")
        if isinstance(finding, dict) and finding.get("title"):
            findings.append(finding)
    return findings


def _registry_for(template: Template, danger_allowances: list[str] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    install_builtins(registry)
    registry.set_security_context(
        scope_policy=_active().scope_policy,
        danger_policy=_active().danger_policy,
        run_allowances=danger_allowances or [],
    )
    for tool in template.tools:
        registry.register(tool)
    return registry


def _manual_registry(tool: Tool, args: dict) -> ToolRegistry:
    """Registry for a single user-initiated tool execution (tools page run,
    imported-tool trial). The active project's scope and danger policies always
    apply; the explicit UI confirmation counts as the danger policy's "ask",
    while "deny" actions still block the run."""
    verdict = evaluate_danger(_active().danger_policy or danger_policy_default(), tool, args)
    allowances = {f"{tool.name}:{verdict.category}"} if verdict.action == "ask" else set()
    registry = ToolRegistry()
    install_builtins(registry)
    registry.set_security_context(
        scope_policy=_active().scope_policy,
        danger_policy=_active().danger_policy,
        run_allowances=allowances,
    )
    return registry


def _get_provider():
    settings = _active().settings
    api_key = settings.get("api_key", "")
    if not api_key:
        return None
    return OpenAICompatibleProvider(settings["base_url"], api_key, settings["model"])


def _get_provider_for(model="", reasoning_effort=""):
    settings = _active().settings
    api_key = settings.get("api_key", "")
    if not api_key:
        return None
    eff = reasoning_effort or settings.get("reasoning_effort", "")
    return OpenAICompatibleProvider(
        settings.get("base_url", ""), api_key, model or settings.get("model", ""), reasoning_effort=eff
    )


class _NotifyingEventLog(EventLog):
    """EventLog that also pushes each appended event to a callback, used for live SSE streaming."""

    def __init__(self, path, sink):
        super().__init__(path)
        self._sink = sink

    def append(self, type, data):
        event = super().append(type, data)
        self._sink({"seq": event.seq, "type": event.type, "data": event.data})
        return event


class _RunStopped(BaseException):
    """Raised inside the background run loop when a stop was requested via /stop."""


class _LiveRun:
    """Thread-safe buffer for events emitted by a background run, consumed by the SSE endpoint."""

    def __init__(self):
        self._lock = threading.Lock()
        self.events: list[dict] = []
        self.done = False
        self.result = None
        self.error = None
        self.queue: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()

    def request_stop(self):
        self._stop.set()

    def stop_requested(self):
        return self._stop.is_set()

    def append(self, event):
        with self._lock:
            self.events.append(event)
        self.queue.put(("event", event))

    def finish(self, result=None, error=None):
        with self._lock:
            self.done = True
            self.result = result
            self.error = error
        self.queue.put(("done", {"result": result, "error": error}))

    def snapshot(self):
        with self._lock:
            return list(self.events), self.done, self.result, self.error


class _StreamingProvider:
    """Wrap a provider so AssistantAgent.respond can stream output unchanged.

    provider.chat() runs stream_chat() and pushes each text delta to a sink while
    still returning the assembled {content, tool_calls} that AssistantAgent expects.
    """

    def __init__(self, provider, sink):
        self.provider = provider
        self.sink = sink

    def chat(self, messages, tools):
        content_parts = []
        forwarded = 0
        for event in self.provider.stream_chat(messages, tools):
            if event["type"] == "delta":
                content_parts.append(event["content"])
                chunk = event.get("content") or ""
                if forwarded < _MAX_STREAM_DELTA_CHARS:
                    room = _MAX_STREAM_DELTA_CHARS - forwarded
                    self.sink({"type": "content_delta", "content": chunk[:room]})
                    forwarded += min(len(chunk), room)
            elif event["type"] == "done":
                return {"content": event["content"], "tool_calls": event["tool_calls"]}
        return {"content": "".join(content_parts), "tool_calls": []}


_MAX_STREAM_DELTA_CHARS = 2000


_live_runs: dict[str, _LiveRun] = {}
_live_lock = threading.Lock()
_install_jobs: dict[str, dict] = {}
_install_lock = threading.Lock()


def _get_live(run_id):
    return _live_runs.get(run_id)


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _job_event_stream(job_id: str):
    import asyncio
    sent = 0
    while True:
        events = list_generation_events(job_id)
        for event in events[sent:]:
            sent += 1
            yield _sse_event({
                "type": event["type"],
                "message": event.get("message"),
                "template": event.get("template"),
                "report": event.get("report"),
            })
        if generation_done(job_id):
            break
        await asyncio.sleep(0.3)


def _execute_run(template, provider, target, autonomous, event_sink=None, self_check=False, danger_allowances=None, run_id="", checkpoint_path=None, run_state=None, prior_context=None):
    """Run a validated template and return (facts, events, report, evolution). event_sink is notified per event."""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "session.jsonl"
        active_log = _NotifyingEventLog(log_path, event_sink) if event_sink else EventLog(log_path)
        registry = _registry_for(template, danger_allowances=danger_allowances)
        agent_provider = _StreamingProvider(provider, event_sink) if event_sink else provider
        if autonomous:
            facts = WorkflowAgent(agent_provider, registry, active_log, approver=None, prior_context=prior_context).run(template, target, cwd=_DATA_ROOT)
        else:
            agent = StageAgent(
                agent_provider, registry, active_log, approver=None,
                skills={s.name: s.content for s in template.skills},
                prior_context=prior_context,
            )
            rs = Executor(template, registry, active_log, run_id=run_id, checkpoint_path=checkpoint_path,
                          exec_store=getattr(_active(), "executions", None)).run(
                target, cwd=_DATA_ROOT, approver=None, agent=agent, run_state=run_state
            )
            facts = rs.facts
        events = [{"seq": e.seq, "type": e.type, "data": e.data} for e in active_log.read()]
    recorded_findings = _recorded_findings_from_events(events)
    report_facts = {**facts, "recorded_findings": recorded_findings} if recorded_findings else facts
    report = None
    try:
        if event_sink is not None:
            report = generate_report_stream(
                provider, report_facts, template,
                on_delta=lambda chunk: event_sink({"type": "report_delta", "content": chunk}),
            )
        else:
            report = generate_report(provider, report_facts, template)
    except Exception:
        report = None
    evolution = {}
    if self_check:
        try:
            units = group_units(events, autonomous=autonomous)
            unit_notes = []
            for unit in units:
                notes = self_check_unit(provider, unit)
                unit_notes.append({"label": unit["label"], "notes": notes})
                if event_sink:
                    event_sink({"type": "self_check", "step": {"label": unit["label"], "stage": unit["label"]}, "notes": notes})
            evolution = evolution_report(provider, template, events, unit_notes, fp_stats=_fp_stats(prior_context))
            if event_sink:
                event_sink({"type": "evolution_complete", "evolution": evolution})
        except Exception:
            evolution = {}
    return facts, events, report, evolution


def _fp_stats(prior_context):
    if not prior_context:
        return None
    fps = [f for f in prior_context.get("prior_findings", []) if f.get("status") == "false_positive"]
    stats = {"known_false_positives": len(prior_context.get("known_false_positives", []))}
    by_target = {}
    by_severity = {}
    for f in fps:
        target = f.get("target") or "unknown"
        severity = f.get("severity") or "unknown"
        by_target[target] = by_target.get(target, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
    if by_target:
        stats["by_target"] = by_target
    if by_severity:
        stats["by_severity"] = by_severity
    return stats


def _tool_tiers_from_events(events) -> dict:
    """Count real/sim tool executions from the run's tool_tier events."""
    tiers = {"real": 0, "sim": 0}
    for event in events or []:
        data = event.get("data") or {} if isinstance(event, dict) else {}
        if isinstance(event, dict) and event.get("type") == "tool_tier" and data.get("tier") in tiers:
            tiers[data["tier"]] += 1
    return tiers


def _append_run_message(session_id: str, run_id: str, report, template, target: str):
    """Write the run result back into the task conversation as an assistant message."""
    if not session_id:
        return
    conv = _active().get_conversation(session_id)
    if conv is None:
        return
    content = report or f"运行完成：{template.name}（{target}）"
    conv["messages"] = list(conv.get("messages", [])) + [{"role": "assistant", "content": content}]
    conv["updated_at"] = datetime.now().isoformat(timespec="seconds")
    conv["last_run_id"] = run_id
    _active().upsert_conversation(conv)


def _run_in_background(run_id, template, target, autonomous, self_check=False, danger_allowances=None, run_state=None, prior_context=None, session_id=""):
    live = _get_live(run_id)
    if live is None:
        return

    def event_sink(event):
        if live.stop_requested():
            raise _RunStopped()
        live.append(event)

    try:
        provider = _get_provider()
        if provider is None:
            raise HTTPException(status_code=400, detail="LLM 未配置；请在设置里填写 API Key")
        facts, events, report, evolution = _execute_run(
            template,
            provider,
            target,
            autonomous,
            event_sink=event_sink,
            self_check=self_check,
            danger_allowances=danger_allowances,
            run_id=run_id,
            checkpoint_path=_active().root / "sessions" / f"{run_id}.state.json",
            run_state=run_state,
            prior_context=prior_context,
        )
        _active().save_run(run_id, {
            "id": run_id,
            "template_id": template.id,
            "target": target,
            "kind": "run",
            "session_id": session_id,
            "output": None,
            "report": report,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "facts": facts,
            "events": events,
            "self_check": self_check,
            "evolution": evolution or {},
            "tool_tiers": _tool_tiers_from_events(events),
        })
        _save_evidence_from_events(_active(), run_id, events, session_id=session_id)
        _persist_evidence_tools(_active(), run_id, session_id, events)
        if report:
            try:
                known_false_positives = (prior_context or {}).get("known_false_positives")
                raw_findings = generate_findings(provider, facts, template, target, known_false_positives=known_false_positives)
            except Exception:
                raw_findings = []
            for idx, finding in enumerate(raw_findings):
                finding["id"] = f"f_{run_id[:8]}_{idx}"
                finding["run_id"] = run_id
                finding["session_id"] = session_id
                _active().save_finding(finding["id"], finding)
        try:
            extracted, _ = extract_assets_from_facts(facts, run_id)
            for asset in extracted:
                _active().assets.upsert_asset(
                    kind=asset["kind"],
                    value=asset["value"],
                    source_run_id=run_id,
                    source_tool=asset.get("source_tool", ""),
                    session_id=session_id,
                )
        except Exception:
            pass
        _append_run_message(session_id, run_id, report, template, target)
        live.finish(result={"id": run_id, "facts": facts, "events": events, "report": report, "evolution": evolution})
    except _RunStopped:
        partial_events = live.snapshot()[0]
        _active().save_run(run_id, {
            "id": run_id,
            "template_id": template.id,
            "target": target,
            "kind": "run",
            "session_id": session_id,
            "output": None,
            "report": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "facts": {},
            "events": partial_events,
            "self_check": self_check,
            "evolution": {},
            "status": "stopped",
            "tool_tiers": _tool_tiers_from_events(partial_events),
        })
        live.finish(error="运行已停止，可在运行态 DAG 中点击「继续」恢复")
    except HTTPException as exc:
        live.finish(error=exc.detail)
    except ApprovalDenied as exc:
        live.finish(error=f"审批被拒绝：{exc}")
    except ToolError as exc:
        live.finish(error=str(exc))
    except Exception as exc:
        live.finish(error=str(exc))
    finally:
        with _live_lock:
            _live_runs.pop(run_id, None)


def _run_conversation_stream(conv_id, job_id, message, confirm=None):
    live = _get_live(job_id)
    if live is None:
        return
    try:
        conv = _active().get_conversation(conv_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        if conv["kind"] != "assistant":
            raise HTTPException(status_code=400, detail="task conversations must use /api/runs")
        real_provider = _get_provider_for(conv.get("model", ""), conv.get("reasoning_effort", ""))
        if real_provider is None:
            raise HTTPException(status_code=400, detail="LLM not configured; set API key in settings")

        prior_messages = list(conv.get("messages", []))
        user_text = (message or "").strip()
        if user_text:
            conv["messages"] = prior_messages + [{"role": "user", "content": user_text}]
            _active().upsert_conversation(conv)

        template_data = _template_store.get(conv.get("template_id", "")) if conv.get("template_id") else None
        template = from_dict(Template, template_data) if template_data else None

        with tempfile.TemporaryDirectory() as td:
            log = _NotifyingEventLog(Path(td) / "s.jsonl", live.append)
            provider = _StreamingProvider(real_provider, live.append)
            agent = AssistantAgent(
                provider, _projects_store(), log,
                template_store=_template_store,
                tool_store=_tool_store,
                skill_store=_skill_store,
                template=template,
            )
            result = agent.respond(user_text, prior_messages, confirm=confirm)

        final_content = result.get("content") or ""
        conv["messages"] = list(conv.get("messages", [])) + [{"role": "assistant", "content": final_content}]
        conv["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _active().upsert_conversation(conv)
        live.finish(result={"content": final_content, "pending": result.get("pending"), "conv_id": conv_id})
    except HTTPException as exc:
        live.finish(error=exc.detail)
    except ToolError as exc:
        live.finish(error=str(exc))
    except Exception as exc:
        live.finish(error=str(exc))


async def _live_run_events(run_id):
    live = _get_live(run_id)
    if live is None:
        return
    replays, done, result, error = live.snapshot()
    for event in replays:
        yield _sse_event(event)
    loop = asyncio.get_running_loop()
    try:
        if not done:
            while True:
                try:
                    kind, payload = await loop.run_in_executor(None, live.queue.get, True, 0.3)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if kind == "event":
                    yield _sse_event(payload)
                elif kind == "done":
                    result = (payload or {}).get("result")
                    error = (payload or {}).get("error")
                    break
                elif kind == "stopped":
                    yield _sse_event({"type": "run_stopped", "run_id": run_id, "message": "运行已停止"})
                    return
        if error:
            yield _sse_event({"type": "error", "run_id": run_id, "message": error})
        else:
            yield _sse_event({
                "type": "run_complete",
                "run_id": run_id,
                "id": run_id,
                "facts": (result or {}).get("facts", {}),
                "report": (result or {}).get("report"),
                "evolution": (result or {}).get("evolution"),
            })
    finally:
        with _live_lock:
            current = _live_runs.get(run_id)
            if current is not None and current.done:
                _live_runs.pop(run_id, None)


async def _conv_stream_events(conv_id, job_id):
    live = _get_live(job_id)
    if live is None:
        return
    replays, done, result, error = live.snapshot()
    for event in replays:
        yield _sse_event(event)
    loop = asyncio.get_running_loop()
    try:
        if not done:
            while True:
                try:
                    kind, payload = await loop.run_in_executor(None, live.queue.get, True, 0.3)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if kind == "event":
                    yield _sse_event(payload)
                elif kind == "done":
                    result = (payload or {}).get("result")
                    error = (payload or {}).get("error")
                    break
        if error:
            yield _sse_event({"type": "error", "conv_id": conv_id, "message": error})
        else:
            yield _sse_event({
                "type": "message_complete",
                "conv_id": conv_id,
                "content": (result or {}).get("content"),
                "pending": (result or {}).get("pending"),
            })
    finally:
        with _live_lock:
            current = _live_runs.get(job_id)
            if current is not None and current.done:
                _live_runs.pop(job_id, None)


async def _stored_run_events(run_id):
    run = _active().runs[run_id]
    for event in run.get("events", []):
        yield _sse_event(event)
    yield _sse_event({
        "type": "run_complete",
        "run_id": run_id,
        "id": run_id,
        "facts": run.get("facts", {}),
        "report": run.get("report"),
    })


def _redact_settings(settings: dict) -> dict:
    redacted = dict(settings or {})
    redacted["has_api_key"] = bool((settings or {}).get("api_key"))
    redacted["api_key"] = ""
    return redacted


def _require_str(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{label} must be a non-empty string")
    return value.strip()



def _run_install_job(job_id: str, requires: list[str]) -> None:
    state = _install_jobs.get(job_id)
    if state is None:
        return

    def on_progress(result: dict) -> None:
        with _install_lock:
            state["results"].append(result)

    try:
        install_toolchain(requires, dry_run=False, on_progress=on_progress)
        with _install_lock:
            state["status"] = "done"
    except Exception as exc:
        with _install_lock:
            state["status"] = "error"
            state["error"] = str(exc)
