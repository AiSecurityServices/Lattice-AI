"""M2-A T1: default template matrix — structure contract + deterministic runs.

Every matrix template must validate as a Template, carry the metadata block,
honour the lite/standard/extensive rules, and finish a full executor run in
deterministic mode (agent=None: no LLM, registry tools fall back to sims or
error facts — the "demo floor" from handoff §7.3).
"""
import tempfile
import urllib.error
from pathlib import Path

import pytest
from lattice_ai import builtin_templates as bt
from lattice_ai.builtins import install_builtins
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.graph import validate_template
from lattice_ai.models import Template, from_dict
from lattice_ai.toolchain_registry import load_registry
from lattice_ai.tools import ToolRegistry

ALL = bt.MATRIX_TEMPLATES
BY_ID = {t["id"]: t for t in ALL}

# Deterministic demo floor (handoff §7.3): runs finish without LLM, without
# real tools and without touching the network — sims degrade to error facts.
_LOCAL_TARGET = "127.0.0.1"


@pytest.fixture(autouse=True)
def _offline_sims(monkeypatch):
    from lattice_ai import builtins as B

    def _offline(*args, **kwargs):
        raise urllib.error.URLError("offline matrix test")

    monkeypatch.setattr(B, "_fetch", _offline)
    monkeypatch.setattr(B, "_crt_sh", _offline)
    monkeypatch.setattr(B, "_hackertarget", _offline)
    monkeypatch.setattr(B, "_dns_brute", _offline)

LITE_IDS = ("matrix-triage-quick", "matrix-web-lite", "matrix-recon-domain-lite")
STANDARD_IDS = (
    "matrix-web-standard", "matrix-web-extensive", "matrix-api-assessment",
    "matrix-recon-domain-standard", "matrix-host-network",
)


def _registry_names():
    names = {e.name for e in load_registry()}
    names.update(t["name"] for t in bt._DECLARED_BUILTIN_TOOLS)
    return names


def test_matrix_has_ten_templates_with_matrix_prefix():
    assert len(ALL) == 10
    assert len(BY_ID) == 10
    assert all(t["id"].startswith("matrix-") for t in ALL)
    assert set(BY_ID) == {
        "matrix-triage-quick", "matrix-web-lite", "matrix-web-standard", "matrix-web-extensive",
        "matrix-api-assessment", "matrix-recon-domain-lite", "matrix-recon-domain-standard",
        "matrix-host-network", "matrix-content-discovery", "matrix-repo-audit",
    }


@pytest.mark.parametrize("template", ALL, ids=lambda t: t["id"])
def test_template_validates_and_carries_metadata(template):
    validate_template(from_dict(Template, template))
    assert template["author"] == "lattice-builtin"
    assert template["depth"] in ("lite", "standard", "extensive", "special")
    assert template["target_type"] in ("web", "api", "domain", "host", "repo")
    assert isinstance(template["tags"], list) and template["tags"]
    assert set(template["description_i18n"]) == {"zh", "en"}
    assert template["description_i18n"]["zh"] == template["summary"]


def test_lite_rules_shallow_no_verify_no_skills():
    for tid in LITE_IDS:
        template = BY_ID[tid]
        assert len(template["stages"]) <= 4, tid
        assert all(stage["id"] != "verify" for stage in template["stages"]), tid
        assert all(not stage.get("skills") for stage in template["stages"]), tid


@pytest.mark.parametrize("tid", STANDARD_IDS)
def test_standard_rules_verify_evidence_gate_and_skills(tid):
    template = BY_ID[tid]
    verify = next(stage for stage in template["stages"] if stage["id"] == "verify")
    gate_names = [gate["name"] for gate in verify.get("gates", [])]
    assert "evidence_complete" in gate_names
    assert verify["gates"][-1]["check"]["key"] == "record_verify.recorded"
    skill_names = {binding["skill"] for stage in template["stages"] for binding in stage.get("skills", [])}
    assert {"web-enumeration", "verification"} <= skill_names


def test_extensive_has_parallel_branches_and_join():
    template = BY_ID["matrix-web-extensive"]
    dependents: dict[str, list[str]] = {}
    for stage in template["stages"]:
        for dep in stage.get("depends_on", []):
            dependents.setdefault(dep, []).append(stage["id"])
    parallel_fanout = {dep: kids for dep, kids in dependents.items() if len(kids) >= 2}
    assert "web_fingerprint" in parallel_fanout  # dir_full ‖ param_fuzz
    join = next(stage for stage in template["stages"] if stage["id"] == "vuln_scan")
    assert set(join["depends_on"]) == {"dir_full", "param_fuzz"}


def test_api_assessment_binds_auth_skill_and_coverage_gate():
    template = BY_ID["matrix-api-assessment"]
    auth = next(stage for stage in template["stages"] if stage["id"] == "auth_test")
    skills = {binding["skill"] for binding in auth.get("skills", [])}
    assert "api-auth-testing" in skills and "finding-format" in skills
    gate = auth["gates"][0]
    assert gate["name"] == "auth_coverage"
    assert gate["check"]["op"] == "or"


def test_every_template_has_gates_and_no_pinned_tier():
    for template in ALL:
        gates = [gate["name"] for stage in template["stages"] for gate in stage.get("gates", [])]
        assert gates, template["id"]
        for stage in template["stages"]:
            for binding in stage.get("tools", []):
                assert binding.get("tier", "any") == "any", template["id"]


def test_bindings_only_use_known_tools():
    known = _registry_names()
    for template in ALL:
        for stage in template["stages"]:
            for binding in stage.get("tools", []):
                assert binding["tool"] in known, (template["id"], binding["tool"])


def test_triple_distinction_across_sampled_templates():
    sampled = [BY_ID[k] for k in ("matrix-web-standard", "matrix-api-assessment", "matrix-content-discovery")]
    stage_shapes = {tuple(stage["id"] for stage in t["stages"]) for t in sampled}
    gate_sets = {
        frozenset(gate["name"] for stage in t["stages"] for gate in stage.get("gates", [])) for t in sampled
    }
    skill_sets = {
        frozenset(binding["skill"] for stage in t["stages"] for binding in stage.get("skills", [])) for t in sampled
    }
    assert len(stage_shapes) == 3
    assert len(gate_sets) == 3
    assert len(skill_sets) == 3


def _registry():
    registry = ToolRegistry()
    install_builtins(registry)
    return registry


def _run_deterministic(template, target):
    template_obj = from_dict(Template, template)
    validate_template(template_obj)
    with tempfile.TemporaryDirectory() as td:
        log = EventLog(Path(td) / "events.jsonl")
        rs = Executor(template_obj, _registry(), log, run_id="matrix-test").run(target)
        events = [entry.type for entry in log.read()]
    return rs, events


@pytest.mark.parametrize("template", ALL, ids=lambda t: t["id"])
def test_deterministic_run_completes_without_llm_or_real_tools(template):
    rs, events = _run_deterministic(template, _LOCAL_TARGET)
    assert "run_started" in events
    assert "run_finished" in events
    assert set(rs.stage_status.values()) <= {"completed", "skipped", "failed"}


def test_repo_audit_runs_against_local_sample_dir():
    sample = Path(__file__).parent / "fixtures" / "sample-repo"
    rs, events = _run_deterministic(BY_ID["matrix-repo-audit"], str(sample))
    assert "run_finished" in events
    dep_scan = rs.facts.get("trivy") or {}
    # trivy 解析器对样例目录可用（真工具在位时产出 findings；缺失时为 error fact，run 不断链）
    assert dep_scan.get("summary") or dep_scan.get("error")
