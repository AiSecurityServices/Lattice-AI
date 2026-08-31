import pytest

from lattice_ai.models import Evidence, Finding, to_dict
from lattice_ai.workspace import Project, ProjectStore


def _seed_settings():
    return {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-test",
    }


def test_project_evidence_and_findings(tmp_path):
    store = ProjectStore(tmp_path / "projects", seed_settings=_seed_settings())
    project = store.active()
    project.save_evidence("evt_1", to_dict(Evidence(id="evt_1", run_id="r", stage_id="s", tool="nmap")))
    project.save_finding("F-1", to_dict(Finding(id="F-1", title="x")))
    reloaded = Project(project.id, project.root)
    assert "evt_1" in reloaded.evidence
    assert "F-1" in reloaded.findings


def test_project_roundtrip(tmp_path):
    p = Project("p", tmp_path / "p")
    p.save_settings({"api_key": "sk-test"})
    p.save_run("r1", {"id": "r1", "facts": {}})
    p.save_current_template_id("demo")

    reloaded = Project("p", tmp_path / "p")
    assert reloaded.settings["api_key"] == "sk-test"
    assert "r1" in reloaded.runs
    assert reloaded.current_template_id == "demo"


def test_project_store_seeds_default(tmp_path):
    store = ProjectStore(tmp_path / "projects", seed_settings=_seed_settings())
    active = store.active()
    assert active.id == "default"
    assert active.name == "默认项目"
    assert active.settings["api_key"] == "sk-test"
    assert active.current_template_id == ""


def test_project_store_crud(tmp_path):
    store = ProjectStore(tmp_path / "projects", seed_settings=_seed_settings())
    project = store.create("My Project")
    assert project.name == "My Project"
    store.switch(project.id)
    assert store.active().id == project.id
    with pytest.raises(ValueError):
        store.delete(project.id)
    store.switch("default")
    store.delete(project.id)
    assert store.get(project.id) is None


def test_project_store_persists_runs(tmp_path):
    store = ProjectStore(tmp_path / "projects", seed_settings=_seed_settings())
    store.active().save_run("r1", {"id": "r1", "kind": "run", "target": "example.com"})
    reloaded = ProjectStore(tmp_path / "projects", seed_settings=_seed_settings())
    assert reloaded.active().runs["r1"]["target"] == "example.com"


def test_project_store_persists_current_template(tmp_path):
    store = ProjectStore(tmp_path / "projects", seed_settings=_seed_settings())
    store.active().save_current_template_id("demo")
    reloaded = ProjectStore(tmp_path / "projects", seed_settings=_seed_settings())
    assert reloaded.active().current_template_id == "demo"


def test_project_conversations_roundtrip(tmp_path):
    p = Project("p", tmp_path / "p")
    assert p.conversations == []
    conv = {"id": "c1", "kind": "assistant", "name": "管理对话 1", "messages": [{"role": "user", "content": "hi"}]}
    p.upsert_conversation(conv)
    p.upsert_conversation({"id": "c2", "kind": "task", "name": "任务 1", "target": "example.com"})
    assert len(p.conversations) == 2
    reloaded = Project("p", tmp_path / "p")
    assert reloaded.get_conversation("c1")["messages"][0]["content"] == "hi"
    reloaded.delete_conversation("c1")
    assert reloaded.get_conversation("c1") is None


def test_project_security_policy_round_trip(tmp_path):
    project = Project("p1", tmp_path)
    project.save_scope_policy({"allow_domains": ["example.com"]})
    project.save_danger_policy({"level": "strict", "whitelist": []})
    project.save_approval_decision({"id": "a1", "tool": "sqlmap", "status": "allowed_once"})

    loaded = Project("p1", tmp_path)
    assert loaded.scope_policy == {"allow_domains": ["example.com"]}
    assert loaded.danger_policy["level"] == "strict"
    assert loaded.approval_logs[0]["id"] == "a1"


def test_project_has_asset_store(tmp_path):
    project = Project("p", tmp_path)
    project.assets.upsert_asset(kind="domain", value="example.com", source_run_id="r1", source_tool="subfinder")
    reloaded = Project("p", tmp_path)
    assert reloaded.assets.list_assets()[0]["value"] == "example.com"


def test_project_load_runs_ignores_checkpoint_state(tmp_path):
    import json
    project = Project("p", tmp_path)
    project.save_run("r1", {"id": "r1", "facts": {}})
    (project.sessions_dir / "r2.state.json").write_text(
        json.dumps({"run_id": "r2", "stage_status": {}}), encoding="utf-8")
    reloaded = Project("p", tmp_path)
    assert sorted(reloaded.runs.keys()) == ["r1"]
