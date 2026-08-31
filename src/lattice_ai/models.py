import dataclasses
from dataclasses import dataclass, field, is_dataclass
from typing import Any, Literal, Optional, Union, get_args, get_origin


def _to_dict(value):
    if is_dataclass(value):
        return {f.name: _to_dict(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, list):
        return [_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_dict(v) for k, v in value.items()}
    return value


def _from_dict(cls, data):
    if data is None:
        return None
    origin = get_origin(cls)
    args = get_args(cls)
    if origin is list:
        (item,) = args
        return [_from_dict(item, x) for x in data]
    if origin is dict:
        value_type = args[1] if len(args) == 2 else Any
        return {k: _from_dict(value_type, v) for k, v in data.items()}
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if data is not None and len(non_none) == 1:
            return _from_dict(non_none[0], data)
    if is_dataclass(cls):
        kwargs = {}
        for f in dataclasses.fields(cls):
            if f.name in data:
                kwargs[f.name] = _from_dict(f.type, data[f.name])
        return cls(**kwargs)
    return data


def to_dict(obj) -> dict:
    return _to_dict(obj)


def from_dict(cls, data):
    return _from_dict(cls, data)


@dataclass
class Tool:
    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    runner: Literal["cli", "builtin", "adapter"] = "cli"
    command: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    approval: Literal["allow", "ask", "deny"] = "allow"
    secret_fields: list[str] = field(default_factory=list)
    adapter: str = ""
    ref: str = ""
    category: str = "general"
    enabled: bool = True


@dataclass
class Evidence:
    id: str
    run_id: str
    stage_id: str
    tool: str
    session_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    hash: str = ""
    superseded: bool = False
    superseded_by_run_id: str = ""


@dataclass
class Finding:
    id: str
    title: str
    run_id: str = ""
    session_id: str = ""
    severity: str = "medium"
    status: str = "pending"
    cwe: str = ""
    cvss: str = ""
    target: str = ""
    confidence: str = "unverified"
    evidence_ids: list[str] = field(default_factory=list)
    summary: str = ""
    impact: str = ""
    remediation: str = ""
    affected_asset: str = ""
    repro_steps: list[str] = field(default_factory=list)
    dedup_key: str = ""
    superseded: bool = False
    superseded_by_run_id: str = ""
    # Evidence-grounding verdict from review.generate_findings (mark/enforce
    # policy): {status: verified|unverified|missing_evidence, detail,
    # matched_snippets}. Empty dict = policy off / legacy finding.
    grounding: dict = field(default_factory=dict)


@dataclass
class Skill:
    name: str
    content: str = ""
    description: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    # Knowledge-base provenance (M3-B): source names the importing pipeline
    # (e.g. "nuclei"), classification carries the template's own scoring
    # fields {cve, cwe, cvss, epss, severity} for display.
    source: str = ""
    classification: dict = field(default_factory=dict)


@dataclass
class ToolBinding:
    tool: str
    key: Optional[str] = None
    condition: Optional[dict[str, Any]] = None
    defaults: dict[str, Any] = field(default_factory=dict)
    args_from: dict[str, str] = field(default_factory=dict)
    note: str = ""
    enabled: bool = True
    tier: str = "any"  # any | real | sim — real: fail loudly when the CLI is missing


@dataclass
class SkillBinding:
    skill: str
    enabled: bool = True


@dataclass
class GateRule:
    name: str
    check: dict[str, Any] = field(default_factory=dict)
    on_fail: str = "block"  # "block" | "warn"


@dataclass
class Stage:
    id: str
    name: str
    goal: str = ""
    depends_on: list[str] = field(default_factory=list)
    optional: bool = False
    condition: Optional[dict[str, Any]] = None
    gates: list[GateRule] = field(default_factory=list)
    tools: list[ToolBinding] = field(default_factory=list)
    skills: list[SkillBinding] = field(default_factory=list)
    completion: Optional[dict[str, Any]] = None
    timeout: float = 300.0


@dataclass
class Template:
    id: str
    name: str
    start: str
    stages: list[Stage] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    summary: str = ""
    version: int = 1
    # matrix metadata (M2-A T2); optional so user templates stay valid
    tags: list[str] = field(default_factory=list)
    depth: str = ""  # lite | standard | extensive | special
    target_type: str = ""  # web | api | domain | host | repo


@dataclass
class RunState:
    run_id: str
    template_id: str
    target: str
    current_stage: Optional[str] = None
    stage_status: dict[str, str] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    checkpoint_version: int = 0
    started_at: str = ""
    updated_at: str = ""
    tool_tiers: dict[str, int] = field(default_factory=lambda: {"real": 0, "sim": 0})
