from lattice_ai.server import migrate_legacy_session_ids
from lattice_ai.workspace import ProjectStore


def _legacy_project(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project = store.active()
    project.save_run("r1", {
        "id": "r1",
        "template_id": "t1",
        "target": "example.com",
        "kind": "run",
        "output": None,
        "report": None,
        "created_at": "2026-08-28T00:00:00",
        "facts": {},
        "events": [],
    })
    project.save_finding("f1", {"id": "f1", "title": "legacy", "run_id": "r1"})
    project.save_evidence("e1", {"id": "e1", "run_id": "r1", "stage_id": "s", "tool": "t"})
    project.assets.upsert_asset(kind="domain", value="example.com", source_run_id="r1")
    return project


def test_migrate_assigns_legacy_records_to_default_session(tmp_path):
    project = _legacy_project(tmp_path)
    migrate_legacy_session_ids(project)

    defaults = [c for c in project.conversations if c.get("is_default")]
    assert len(defaults) == 1
    default_id = defaults[0]["id"]
    assert defaults[0]["kind"] == "task"

    assert project.runs["r1"]["session_id"] == default_id
    assert project.findings["f1"]["session_id"] == default_id
    assert project.evidence["e1"]["session_id"] == default_id
    assert all(a["session_id"] == default_id for a in project.assets.list_assets())


def test_migrate_is_idempotent(tmp_path):
    project = _legacy_project(tmp_path)
    migrate_legacy_session_ids(project)
    conversation_count = len(project.conversations)
    migrate_legacy_session_ids(project)
    assert len(project.conversations) == conversation_count


def test_migrate_keeps_existing_session_records(tmp_path):
    project = _legacy_project(tmp_path)
    project.save_run("r2", {
        "id": "r2",
        "template_id": "t1",
        "target": "other.example",
        "kind": "run",
        "output": None,
        "report": None,
        "created_at": "2026-08-29T00:00:00",
        "facts": {},
        "events": [],
        "session_id": "conv_existing",
    })
    migrate_legacy_session_ids(project)
    assert project.runs["r2"]["session_id"] == "conv_existing"
    assert project.runs["r1"]["session_id"] != "conv_existing"
