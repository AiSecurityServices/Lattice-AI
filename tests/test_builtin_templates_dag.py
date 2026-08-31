import json

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.graph import validate_template
from lattice_ai.models import Template, from_dict


def test_builtin_templates_are_valid_dags():
    for template in (
        server._LITE_PENTEST_TEMPLATE,
    ):
        assert "transitions" not in template
        assert template["start"] in {s["id"] for s in template["stages"]}
        validate_template(from_dict(Template, template))


def test_builtin_template_stages_have_depends_on():
    stages = {s["id"]: s for s in server._LITE_PENTEST_TEMPLATE["stages"]}
    assert stages["normalize"]["depends_on"] == []
    assert stages["liveness"]["depends_on"] == ["normalize"]
    assert stages["subdomain"]["depends_on"] == ["liveness"]
    assert stages["web_fingerprint"]["depends_on"] == ["ports"]
    assert stages["js_analyze"]["depends_on"] == ["js_collect"]
    assert stages["dep_cve"]["depends_on"] == ["js_analyze"]


def test_matrix_extensive_template_is_a_large_dag_with_branches_and_gates():
    from lattice_ai.builtin_templates import MATRIX_TEMPLATES

    tpl = next(t for t in MATRIX_TEMPLATES if t["id"] == "matrix-web-extensive")
    assert len(tpl["stages"]) >= 10
    parsed = from_dict(Template, tpl)
    validate_template(parsed)

    stages = {st["id"]: st for st in tpl["stages"]}
    assert any(st.get("gates") for st in tpl["stages"])
    # "extensive" = parallel deep-recon branches (dir_full ∥ param_fuzz)
    # converging through vuln_scan into verify
    assert stages["dir_full"]["depends_on"] == ["web_fingerprint"]
    assert stages["param_fuzz"]["depends_on"] == ["web_fingerprint"]
    assert "vuln_scan" in stages["verify"]["depends_on"]


def test_marketplace_offers_the_lite_template():
    entry = server._MARKETPLACE["builtin-full-pentest-lite"]
    assert entry["template"]["id"] == "builtin-full-pentest-lite"
    assert entry["requires_tools"] == []


def test_legacy_builtin_templates_are_backed_up(tmp_path, monkeypatch):
    from lattice_ai.library import TemplateStore

    store = TemplateStore(tmp_path / "templates")
    legacy = {
        "id": "builtin-info-gathering",
        "name": "信息收集（旧版）",
        "start": "a",
        "stages": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "transitions": [{"id": "e1", "source": "a", "target": "b"}],
        "tools": [],
        "skills": [],
    }
    store.save("builtin-full-pentest-lite", legacy)
    monkeypatch.setattr(rt, "_template_store", store)
    server._backup_legacy_templates()
    backup_path = tmp_path / "templates" / ".backup" / "builtin-full-pentest-lite.json"
    assert backup_path.exists()
    backed_up = json.loads(backup_path.read_text(encoding="utf-8"))
    assert "transitions" in backed_up


def test_seed_replaces_stored_legacy_with_chinese_descriptions(tmp_path, monkeypatch):
    from lattice_ai.library import SkillStore, TemplateStore, ToolStore

    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    legacy = {
        "id": "builtin-info-gathering",
        "name": "信息收集（旧版）",
        "start": "normalize",
        "stages": [
            {"id": "normalize", "name": "目标规范化"},
            {"id": "liveness", "name": "存活发现"},
        ],
        "transitions": [{"id": "e1", "source": "normalize", "target": "liveness"}],
        "tools": [{"name": "dnsx", "description": "内置轻量近似：DNS 记录解析（不等于真实 dnsx）", "runner": "builtin"}],
        "skills": [],
    }
    template_store.save("builtin-full-pentest-lite", legacy)
    monkeypatch.setattr(rt, "_template_store", template_store)
    monkeypatch.setattr(rt, "_tool_store", tool_store)
    monkeypatch.setattr(rt, "_skill_store", skill_store)
    server._seed_global_assets()
    updated = template_store.get("builtin-full-pentest-lite")
    assert "transitions" not in updated
    assert any(s["id"] == "liveness" and s["depends_on"] == ["normalize"] for s in updated["stages"])
    assert (tmp_path / "templates" / ".backup" / "builtin-full-pentest-lite.json").exists()
