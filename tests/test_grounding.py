import json
import time

import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.models import Finding, from_dict, to_dict
from lattice_ai.workspace import ProjectStore

from lattice_ai import grounding
from lattice_ai.grounding import set_policy, verify_grounding
from lattice_ai.report_export import export_report
from lattice_ai.review import generate_findings


class FakeProvider:
    def __init__(self, content):
        self.content = content
        self.last_prompt = ""

    def chat(self, messages, tools=None):
        self.last_prompt = messages[0]["content"]
        return {"content": self.content, "tool_calls": []}


def _evidence(text):
    return {"id": "ev1", "result": {"stdout": text}}


def test_verbatim_claim_matches_ignoring_case_and_spacing():
    finding = {
        "evidence_ids": ["ev1"],
        "summary": "The   ADMIN Panel is reachable at /admin on port 8080.",
    }
    result = verify_grounding(finding, {"ev1": _evidence("scan: the admin panel is reachable\nat /admin on port 8080")})
    assert result.status == "verified"
    assert result.matched_snippets


def test_cjk_claim_matches():
    finding = {"evidence_ids": ["ev1"], "summary": "80端口开放，状态open，版本nginx 1.18。"}
    result = verify_grounding(finding, {"ev1": _evidence("80端口开放\n状态: open, 版本: nginx 1.18")})
    assert result.status == "verified"


def test_fabricated_claim_is_unverified():
    finding = {"evidence_ids": ["ev1"], "summary": "数据库中存在 1 万条明文信用卡记录。"}
    result = verify_grounding(finding, {"ev1": _evidence("port 80 open, server nginx")})
    assert result.status == "unverified"
    assert not result.matched_snippets


def test_line_envelope_tolerates_small_divergence():
    evidence = _evidence("admin password is hunter2 for the staging service")
    finding = {"evidence_ids": ["ev1"], "summary": "admin password is hunter2 for the staging serv1ce"}
    result = verify_grounding(finding, {"ev1": evidence})
    assert result.status == "verified"


def test_partial_match_is_unverified():
    evidence = _evidence("port 80 open, server nginx")
    finding = {
        "evidence_ids": ["ev1"],
        "summary": "port 80 open, server nginx\nthe service leaks internal database credentials",
    }
    result = verify_grounding(finding, {"ev1": evidence})
    assert result.status == "unverified"
    assert "1/2" in result.detail


def test_missing_evidence_ids_and_unknown_ids():
    result = verify_grounding({"summary": "a claim long enough to check"}, {})
    assert result.status == "missing_evidence"

    finding = {"evidence_ids": ["nope"], "summary": "a claim long enough to check"}
    result = verify_grounding(finding, {"ev1": _evidence("a claim long enough to check")})
    assert result.status == "missing_evidence"
    assert "nope" in result.detail


def test_redacted_sentences_are_skipped():
    finding = {
        "evidence_ids": ["ev1"],
        "summary": "[REDACTED]\nthe admin panel is reachable at /admin on port 8080",
    }
    result = verify_grounding(finding, {"ev1": _evidence("the admin panel is reachable at /admin on port 8080")})
    assert result.status == "verified"
    assert "脱敏" in result.detail


def test_policy_switches_mark_enforce_off():
    provider = FakeProvider(json.dumps([{
        "title": "编造的发现",
        "severity": "high",
        "confidence": "high",
        "summary": "数据库中存在 1 万条明文信用卡记录。",
        "evidence": ["ports"],
    }], ensure_ascii=False))
    facts = {"ports": {"stdout": "80,443 open"}}

    set_policy("mark")
    findings = generate_findings(provider, facts, {"name": "t"}, "example.com")
    assert findings[0]["grounding"]["status"] == "unverified"
    assert findings[0]["confidence"] == "unverified"
    assert findings[0]["status"] != "rejected"

    set_policy("enforce")
    findings = generate_findings(provider, facts, {"name": "t"}, "example.com")
    assert findings[0]["status"] == "rejected"
    assert findings[0]["grounding"]["status"] == "unverified"

    set_policy("off")
    findings = generate_findings(provider, facts, {"name": "t"}, "example.com")
    assert "grounding" not in findings[0]

    set_policy("mark")
    with pytest.raises(ValueError):
        set_policy("bogus")


def test_generate_findings_defaults_to_mark_and_maps_facts_as_evidence():
    provider = FakeProvider(json.dumps([{
        "title": "端口开放",
        "summary": "扫描发现目标主机 80 端口处于开放状态。",
        "evidence": ["ports"],
    }], ensure_ascii=False))
    facts = {"ports": {"stdout": "扫描发现目标主机 80 端口处于开放状态"}}
    findings = generate_findings(provider, facts, {"name": "t"}, "example.com")
    assert findings[0]["grounding"]["status"] == "verified"
    assert findings[0]["evidence_ids"] == ["ports"]
    assert "evidence" in provider.last_prompt
    assert grounding.get_policy() == "mark"


def test_report_export_includes_grounding_stats():
    run = {"id": "run1", "target": "example.com"}
    findings = [
        {"id": "f1", "title": "ok", "status": "confirmed", "evidence_ids": ["e1"],
         "grounding": {"status": "verified", "detail": "", "matched_snippets": []}},
        {"id": "f2", "title": "bad", "status": "rejected", "evidence_ids": [],
         "grounding": {"status": "missing_evidence", "detail": "", "matched_snippets": []}},
    ]
    markdown = export_report(run, [], findings, "demo", "md")
    assert "Grounding: 1 verified / 0 unverified / 1 missing_evidence" in markdown
    html = export_report(run, [], findings, "demo", "html")
    assert "1 verified / 0 unverified / 1 missing_evidence" in html
    payload = json.loads(export_report(run, [], findings, "demo", "json"))
    assert payload["grounding"] == {"verified": 1, "unverified": 0, "missing_evidence": 1}


# ---------- T0: grounding survives the full persistence chain ----------

class _RunFakeProvider:
    def chat(self, messages, tools=None):
        return {"content": "[]", "tool_calls": []}


def test_finding_model_roundtrips_grounding():
    data = {
        "id": "f1",
        "title": "X",
        "grounding": {"status": "verified", "detail": "d", "matched_snippets": ["s"]},
    }
    finding = from_dict(Finding, data)
    assert finding.grounding["status"] == "verified"
    # to_dict is symmetric; legacy findings without the key get an empty dict
    assert to_dict(finding)["grounding"]["status"] == "verified"
    assert from_dict(Finding, {"id": "f2", "title": "Y"}).grounding == {}


def test_generate_findings_to_api_findings_chain(tmp_path, monkeypatch):
    """Full chain: generate_findings (with grounding) → background run
    persistence → GET /api/findings returns grounding.status."""
    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    store = ProjectStore(tmp_path / "projects")
    monkeypatch.setattr(rt, "_template_store", template_store)
    monkeypatch.setattr(rt, "_tool_store", tool_store)
    monkeypatch.setattr(rt, "_skill_store", skill_store)
    monkeypatch.setattr(rt, "_projects_store", lambda: store)

    tpl = {
        "id": "t1",
        "name": "demo",
        "start": "a",
        "stages": [{"id": "a", "name": "A", "depends_on": []}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
        "skills": [],
    }
    template_store.save("t1", tpl)

    def fake_execute(template, provider, target, autonomous, **kwargs):
        return {}, [], "# Report", {}

    def fake_findings(provider, facts, template, target="", known_false_positives=None):
        return [
            {
                "title": "已核验发现",
                "severity": "high",
                "status": "confirmed",
                "grounding": {"status": "verified", "detail": "命中", "matched_snippets": ["s"]},
            },
            {
                "title": "编造发现",
                "severity": "medium",
                "grounding": {"status": "unverified", "detail": "未命中", "matched_snippets": []},
            },
        ]

    monkeypatch.setattr(rt, "_execute_run", fake_execute)
    monkeypatch.setattr(rt, "generate_findings", fake_findings)
    monkeypatch.setattr(rt, "_get_provider", lambda: _RunFakeProvider())

    client = TestClient(server.app)
    started = client.post("/api/runs", json={"template": tpl, "target": "example.com"})
    assert started.status_code == 200

    findings = []
    for _ in range(200):
        findings = client.get("/api/findings").json()["findings"]
        if len(findings) >= 2:
            break
        time.sleep(0.05)
    assert len(findings) == 2
    by_title = {f["title"]: f for f in findings}
    assert by_title["已核验发现"]["grounding"]["status"] == "verified"
    assert by_title["编造发现"]["grounding"]["status"] == "unverified"
    # model round-trip keeps the field for any future from_dict normalization
    assert from_dict(Finding, by_title["已核验发现"]).grounding["status"] == "verified"
