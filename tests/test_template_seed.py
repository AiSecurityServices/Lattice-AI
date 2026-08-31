"""M3-B T4.4: cold-start regression — the first request to GET /api/templates
must seed and list the builtin matrix templates.

Lives in its own module because the seeding depends on the REAL
runtime._projects_store (other test modules autouse-patch it)."""

import pytest
from fastapi.testclient import TestClient

from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai import tools as tools_module


@pytest.fixture
def cold_runtime(tmp_path, monkeypatch):
    """A runtime where no project store has initialized yet and the library
    stores point at an empty temp dir."""
    monkeypatch.setattr(rt, "_store", None)
    monkeypatch.setattr(rt, "_template_store", TemplateStore(tmp_path / "templates"))
    monkeypatch.setattr(rt, "_tool_store", ToolStore(tmp_path / "tools"))
    monkeypatch.setattr(rt, "_skill_store", SkillStore(tmp_path / "skills"))
    monkeypatch.setattr(rt, "_PROJECTS_ROOT", tmp_path / "projects")
    # Initializing the real project store registers the go bin dir in the
    # module-level _EXTRA_TOOL_PATHS; keep that mutation sandboxed so later
    # tests don't suddenly "find" real binaries (breaks fallback tests).
    monkeypatch.setattr(tools_module, "_EXTRA_TOOL_PATHS", [])


def test_first_request_lists_seeded_matrix_templates(cold_runtime):
    client = TestClient(server.app)  # first request is the GET itself
    items = client.get("/api/templates").json()["templates"]
    assert len(items) >= 10
    names = {item["id"] for item in items}
    assert any(template_id.startswith("matrix-") or "web" in template_id for template_id in names)


def test_repeated_request_is_stable(cold_runtime):
    client = TestClient(server.app)
    first = client.get("/api/templates").json()["templates"]
    second = client.get("/api/templates").json()["templates"]
    assert len(first) == len(second) >= 10
