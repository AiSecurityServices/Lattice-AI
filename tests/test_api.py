import json
import sys

import pytest
from fastapi.testclient import TestClient

from lattice_ai import preferences
from lattice_ai import runtime as rt
from lattice_ai import server
from lattice_ai.graph import validate_template
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.models import Template, from_dict, to_dict
from lattice_ai.recipes import load_bundled_recipes
from lattice_ai.workspace import ProjectStore


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    template_store.save(server._LITE_PENTEST_TEMPLATE["id"], server._LITE_PENTEST_TEMPLATE)
    for name, data in server._DEFAULT_SKILLS.items():
        skill_store.save(name, data)
    for recipe in load_bundled_recipes():
        tool_store.save(recipe.name, to_dict(recipe))
    store = ProjectStore(
        tmp_path / "projects",
        seed_settings={"provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": ""},
    )
    monkeypatch.setattr(rt, "_template_store", template_store)
    monkeypatch.setattr(rt, "_tool_store", tool_store)
    monkeypatch.setattr(rt, "_skill_store", skill_store)
    monkeypatch.setattr(rt, "_projects_store", lambda: store)
    yield


client = TestClient(server.app)


def test_builtin_templates_validate():
    validate_template(from_dict(Template, server._LITE_PENTEST_TEMPLATE))


def test_evidence_and_findings_endpoints():
    assert client.get("/api/evidence").status_code == 200
    assert client.get("/api/findings").status_code == 200
    assert client.get("/api/logs").status_code == 200


def test_assets_endpoints():
    assert client.get("/api/assets").status_code == 200
    assert client.get("/api/assets/graph").status_code == 200


def test_scope_defaults_when_unconfigured():
    r = client.get("/api/scope")
    assert r.status_code == 200
    body = r.json()
    for key in ("allow_domains", "allow_ips", "allow_cidrs", "allow_ports", "allow_url_prefixes"):
        assert body[key] == []


def test_replay_endpoint_unknown_run():
    assert client.get("/api/runs/nope/replay").status_code == 404


def test_replay_endpoint_paginates():
    run_id = "r-replay"
    rt._active().runs[run_id] = {
        "id": run_id,
        "facts": {},
        "events": [{"seq": 1, "type": "a", "data": {}}, {"seq": 2, "type": "b", "data": {}}],
    }
    r = client.get(f"/api/runs/{run_id}/replay", params={"after": 0, "limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["seq"] == 1
    assert body["next_after"] == 1
    assert body["has_more"] is True


def test_ingest_assets_endpoint():
    run_id = "r-ingest"
    rt._active().runs[run_id] = {
        "id": run_id,
        "facts": {"naabu": {"target": "203.0.113.10", "open_ports": [80]}},
    }
    r = client.post("/api/assets/ingest", json={"run_id": run_id})
    assert r.status_code == 200
    body = r.json()
    assert body["added"] >= 2
    assets = client.get("/api/assets").json()["assets"]
    kinds = {a["kind"] for a in assets}
    assert "ip" in kinds
    assert "port" in kinds
    assert client.post("/api/assets/ingest", json={"run_id": "nope"}).status_code == 404


def test_diff_endpoint():
    rt._active().runs["rb"] = {"id": "rb", "facts": {}, "events": []}
    rt._active().runs["rh"] = {"id": "rh", "facts": {}, "events": []}
    rt._active().assets.upsert_asset(kind="domain", value="example.com", source_run_id="rb")
    rt._active().assets.upsert_asset(kind="ip", value="203.0.113.10", source_run_id="rh")
    r = client.post("/api/runs/diff", json={"base_run_id": "rb", "head_run_id": "rh"})
    assert r.status_code == 200
    body = r.json()
    assert body["base_run_id"] == "rb"
    assert body["head_run_id"] == "rh"
    assert [a["value"] for a in body["assets"]["added"]] == ["203.0.113.10"]
    assert [a["value"] for a in body["assets"]["removed"]] == ["example.com"]
    assert client.post("/api/runs/diff", json={"base_run_id": "rb", "head_run_id": "rb"}).status_code == 400
    assert client.post("/api/runs/diff", json={"base_run_id": "rb", "head_run_id": "nope"}).status_code == 404


def test_run_auto_ingests_assets(monkeypatch):
    import time

    def fake_install(registry):
        from lattice_ai.builtins import install_builtins as real_install_builtins

        real_install_builtins(registry)
        registry.register_builtin(
            "recon_naabu",
            "fake naabu",
            {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
            {},
            lambda args: {"target": args.get("target", ""), "open_ports": [80, 443]},
        )

    monkeypatch.setattr(rt, "install_builtins", fake_install)
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "recon_naabu", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    tpl = {
        "id": "t1",
        "name": "demo",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "recon_naabu", "key": "naabu", "defaults": {"target": "203.0.113.10"}}]}],
        "tools": [{"name": "recon_naabu", "description": "fake", "runner": "builtin"}],
    }
    started = client.post("/api/runs", json={"template": tpl, "target": "203.0.113.10"})
    assert started.status_code == 200
    run_id = started.json()["id"]
    for _ in range(200):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail.get("report") is not None:
            break
        time.sleep(0.05)
    assets = client.get("/api/assets").json()["assets"]
    assert any(a["kind"] == "ip" and a["value"] == "203.0.113.10" for a in assets)
    assert any(a["kind"] == "port" and a["value"] == "80" for a in assets)


def test_scope_endpoint_round_trip():
    put = client.put("/api/scope", json={"allow_domains": ["example.com"]})
    assert put.status_code == 200
    get = client.get("/api/scope")
    assert get.json()["allow_domains"] == ["example.com"]


def test_report_export_unknown_run_is_404():
    client.put("/api/scope", json={})
    response = client.get("/api/reports/nope?format=json")
    assert response.status_code == 404


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_template_crud():
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    r = client.put("/api/templates/t1", json=tpl)
    assert r.status_code == 200
    assert client.get("/api/templates/t1").json()["id"] == "t1"
    ids = [t["id"] for t in client.get("/api/templates").json()["templates"]]
    assert "t1" in ids
    assert client.delete("/api/templates/t1").status_code == 200
    assert client.get("/api/templates/t1").status_code == 404


def test_invalid_template_rejected():
    tpl = {"id": "t1", "name": "demo", "start": "missing", "stages": [{"id": "a", "name": "a"}], "tools": []}
    assert client.put("/api/templates/t1", json=tpl).status_code == 400


def test_run_endpoint(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    tpl = {
        "id": "t1",
        "name": "demo",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    r = client.post("/api/run", json={"template": tpl, "target": "example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["facts"]["out"] == {"value": "hi"}
    assert body["events"][0]["type"] == "run_started"
    assert body["events"][-1]["type"] == "run_finished"


def test_tools_endpoint():
    r = client.get("/api/tools")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["tools"]]
    assert "echo" in names


def test_run_unknown_builtin_returns_400():
    tpl = {
        "id": "t1",
        "name": "demo",
        "start": "a",
        "stages": [{"id": "a", "name": "a"}],
        "tools": [{"name": "nope", "description": "nope", "runner": "builtin"}],
    }
    r = client.post("/api/run", json={"template": tpl, "target": "example.com"})
    assert r.status_code == 400


def test_put_unknown_builtin_returns_400():
    tpl = {
        "id": "t1",
        "name": "demo",
        "start": "a",
        "stages": [{"id": "a", "name": "a"}],
        "tools": [{"name": "nope", "description": "nope", "runner": "builtin"}],
    }
    r = client.put("/api/templates/t1", json=tpl)
    assert r.status_code == 400


def test_marketplace_list():
    from lattice_ai.builtin_templates import MATRIX_TEMPLATE_IDS

    r = client.get("/api/marketplace")
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()["templates"]}
    assert ids == set(MATRIX_TEMPLATE_IDS) | {"builtin-full-pentest-lite", "builtin-web-full"}


def test_marketplace_install():
    r = client.post("/api/marketplace/builtin-full-pentest-lite/install")
    assert r.status_code == 200
    assert client.get("/api/templates/builtin-full-pentest-lite").status_code == 200


def test_tools_include_recipes():
    names = [t["name"] for t in client.get("/api/tools").json()["tools"]]
    assert "echo" in names
    assert "nmap" in names


def test_skills_crud():
    names = [s["name"] for s in client.get("/api/skills").json()["skills"]]
    assert "recon-basics" in names
    assert client.post("/api/skills", json={"name": "xss", "description": "xss", "category": "web", "tags": ["xss"], "content": "# XSS"}).status_code == 200
    assert any(s["name"] == "xss" for s in client.get("/api/skills").json()["skills"])
    assert client.delete("/api/skills/xss").status_code == 200


def test_settings_has_keys():
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert "base_url" in r.json()
    assert "model" in r.json()


def test_run_history(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    run_id = client.post("/api/run", json={"template": tpl, "target": "example.com"}).json()["id"]
    assert any(r["id"] == run_id for r in client.get("/api/runs").json()["runs"])
    assert client.get(f"/api/runs/{run_id}").status_code == 200


def test_start_run_and_stream_events(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    started = client.post("/api/runs", json={"template": tpl, "target": "example.com"})
    assert started.status_code == 200
    run_id = started.json()["id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as res:
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        body = "".join(res.iter_text())
    assert json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])["type"] == "run_started"
    assert "run_complete" in body
    # the run is persisted after completion
    stored = client.get(f"/api/runs/{run_id}")
    assert stored.status_code == 200
    assert stored.json()["kind"] == "run"


def test_run_events_unknown_404():
    assert client.get("/api/runs/does-not-exist/events").status_code == 404


def test_start_run_requires_provider(monkeypatch):
    monkeypatch.setattr(rt, "_get_provider", lambda: None)
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    r = client.post("/api/runs", json={"template": tpl, "target": "example.com"})
    assert r.status_code == 400


def test_stored_run_events_replay(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    run_id = client.post("/api/run", json={"template": tpl, "target": "example.com"}).json()["id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as res:
        body = "".join(res.iter_text())
    assert "run_started" in body
    assert "run_complete" in body


def test_groups_crud():
    assert client.get("/api/groups").json() == {"tool_groups": [], "skill_groups": []}

    created = client.post("/api/groups", json={"kind": "tool", "name": "Recon"})
    assert created.status_code == 200
    group = created.json()
    assert group["id"] == "tg-01"
    assert group["name"] == "Recon"
    assert group["members"] == []

    # duplicate name rejected
    assert client.post("/api/groups", json={"kind": "tool", "name": "Recon"}).status_code == 400

    # rename
    renamed = client.put(f"/api/groups/{group['id']}", json={"kind": "tool", "name": "Discovery"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Discovery"

    # members
    updated = client.put(f"/api/groups/{group['id']}/members", json={"kind": "tool", "members": ["dnsx", "httpx", "dnsx"]})
    assert updated.status_code == 200
    assert updated.json()["members"] == ["dnsx", "httpx"]

    got = client.get("/api/groups").json()["tool_groups"]
    assert got[0]["name"] == "Discovery"
    assert got[0]["members"] == ["dnsx", "httpx"]

    # delete
    assert client.delete(f"/api/groups/{group['id']}?kind=tool").status_code == 200
    assert client.get("/api/groups").json()["tool_groups"] == []


def test_groups_skill_kind_and_errors():
    created = client.post("/api/groups", json={"kind": "skill", "name": "Reporting"})
    assert created.status_code == 200
    group = created.json()
    assert group["id"] == "sg-01"

    # unknown group
    assert client.put("/api/groups/nope", json={"kind": "skill", "name": "x"}).status_code == 404
    assert client.delete("/api/groups/nope?kind=skill").status_code == 404
    # bad kind
    assert client.post("/api/groups", json={"kind": "bogus", "name": "x"}).status_code == 400


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, tools):
        return self.responses.pop(0)

    def stream_chat(self, messages, tools):
        r = self.responses.pop(0)
        content = r.get("content") or ""
        if content:
            yield {"type": "delta", "content": content}
        yield {"type": "done", "content": content, "tool_calls": r.get("tool_calls") or []}


def test_chat_endpoint(monkeypatch):
    monkeypatch.setattr(rt, "_get_provider", lambda: _FakeProvider([{"content": "hi", "tool_calls": []}]))
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    r = client.post("/api/chat", json={"template": tpl, "message": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "hi"
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["kind"] == "chat"
    assert run["target"] == "hello"
    assert run["output"] == "hi"


def test_chat_requires_provider(monkeypatch):
    monkeypatch.setattr(rt, "_get_provider", lambda: None)
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    r = client.post("/api/chat", json={"template": tpl, "message": "hello"})
    assert r.status_code == 400


def test_assistant_endpoint(monkeypatch):
    monkeypatch.setattr(rt, "_get_provider", lambda: _FakeProvider([{"content": "hi", "tool_calls": []}]))
    r = client.post("/api/assistant", json={"message": "hello"})
    assert r.status_code == 200
    assert r.json()["content"] == "hi"


def test_project_crud():
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()["current"] == "default"
    assert any(p["id"] == "default" for p in r.json()["projects"])

    r = client.post("/api/projects", json={"name": "My Project"})
    assert r.status_code == 200
    project_id = r.json()["id"]
    assert client.get(f"/api/projects/{project_id}").status_code == 200

    r = client.put("/api/projects/current", json={"id": project_id})
    assert r.status_code == 200
    assert r.json()["current"] == project_id
    assert client.get("/api/templates").json()["templates"][0]["id"] == "builtin-full-pentest-lite"

    client.put("/api/projects/current", json={"id": "default"})
    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    assert client.get(f"/api/projects/{project_id}").status_code == 404


def test_cannot_delete_active_project():
    assert client.delete("/api/projects/default").status_code == 400


def test_rename_project():
    project_id = client.post("/api/projects", json={"name": "Temp"}).json()["id"]
    r = client.post(f"/api/projects/{project_id}/rename", json={"name": "Renamed"})
    assert r.status_code == 200
    names = {p["id"]: p["name"] for p in client.get("/api/projects").json()["projects"]}
    assert names[project_id] == "Renamed"


def test_run_autonomous_uses_agent(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([{"content": "ok", "tool_calls": []}, {"content": "# Report", "tool_calls": []}]),
    )
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    r = client.post("/api/run", json={"template": tpl, "target": "example.com", "autonomous": True})
    assert r.status_code == 200
    types = [e["type"] for e in r.json()["events"]]
    assert "agent_message" in types


def test_run_requires_provider(monkeypatch):
    monkeypatch.setattr(rt, "_get_provider", lambda: None)
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    r = client.post("/api/run", json={"template": tpl, "target": "example.com"})
    assert r.status_code == 400


def test_run_returns_report(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([{"content": "ok", "tool_calls": []}, {"content": "# Report", "tool_calls": []}]),
    )
    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    r = client.post("/api/run", json={"template": tpl, "target": "example.com"})
    assert r.status_code == 200
    assert r.json()["report"] == "# Report"


def test_chat_accepts_facts(monkeypatch):
    monkeypatch.setattr(rt, "_get_provider", lambda: _FakeProvider([{"content": "hi", "tool_calls": []}]))
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    r = client.post("/api/chat", json={"template": tpl, "message": "analyze", "facts": {"ports": {"stdout": "80"}}})
    assert r.status_code == 200
    assert r.json()["facts"]["ports"]["stdout"] == "80"


def test_update_tool():
    tool = {
        "name": "nuclei",
        "description": "Updated scan",
        "runner": "cli",
        "command": ["nuclei", "-u", "{target}"],
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
    }
    r = client.put("/api/tools/nuclei", json=tool)
    assert r.status_code == 200
    names = {t["name"]: t for t in client.get("/api/tools").json()["tools"]}
    assert names["nuclei"]["description"] == "Updated scan"


def test_run_tool_endpoint():
    tool = {"name": "echo", "description": "echo", "runner": "builtin"}
    r = client.post("/api/tools/run", json={"tool": tool, "args": {"msg": "hi"}})
    assert r.status_code == 200
    assert r.json()["value"] == "hi"


def test_run_tool_invalid_returns_400():
    tool = {"name": "x", "description": "x", "runner": "cli", "command": ["nope"], "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}}
    r = client.post("/api/tools/run", json={"tool": tool, "args": {}})
    assert r.status_code == 400


def test_clone_template():
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    client.put("/api/templates/t1", json=tpl)
    r = client.post("/api/templates/t1/clone")
    assert r.status_code == 200
    clone_id = r.json()["id"]
    assert clone_id != "t1"
    assert client.get(f"/api/templates/{clone_id}").json()["name"] == "demo（副本）"


def test_rename_template():
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    client.put("/api/templates/t1", json=tpl)
    r = client.post("/api/templates/t1/rename", json={"name": "renamed"})
    assert r.status_code == 200
    assert client.get("/api/templates/t1").json()["name"] == "renamed"


def test_template_tools_scope():
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": [], "skills": []}
    client.put("/api/templates/t1", json=tpl)
    assert client.get("/api/templates/t1/tools").json()["tools"] == []
    tool = {"name": "nmap", "description": "scan", "runner": "cli", "command": ["nmap"], "parameters": {"type": "object", "properties": {}, "required": []}}
    r = client.put("/api/templates/t1/tools/nmap", json=tool)
    assert r.status_code == 200
    assert "nmap" in [t["name"] for t in client.get("/api/templates/t1/tools").json()["tools"]]
    assert client.delete("/api/templates/t1/tools/nmap").status_code == 200
    assert "nmap" not in [t["name"] for t in client.get("/api/templates/t1/tools").json()["tools"]]


def test_template_skills_scope():
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": [], "skills": []}
    client.put("/api/templates/t1", json=tpl)
    skill = {"name": "recon", "description": "recon"}
    r = client.put("/api/templates/t1/skills/recon", json=skill)
    assert r.status_code == 200
    assert "recon" in [s["name"] for s in client.get("/api/templates/t1/skills").json()["skills"]]
    assert client.delete("/api/templates/t1/skills/recon").status_code == 200
    assert "recon" not in [s["name"] for s in client.get("/api/templates/t1/skills").json()["skills"]]


def test_project_current_template():
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    client.put("/api/templates/t1", json=tpl)
    assert client.get("/api/projects/current").json()["current_template_id"] == ""
    r = client.put("/api/projects/current/template", json={"template_id": "t1"})
    assert r.status_code == 200
    assert r.json()["current_template_id"] == "t1"
    assert client.get("/api/projects/current").json()["current_template_id"] == "t1"
    assert client.put("/api/projects/current/template", json={"template_id": "nope"}).status_code == 404


def test_generation_endpoint_description(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": json.dumps({"summary": "扫描器", "tools": [], "skills": [], "capabilities": [], "dependencies": [], "confidence": "low"}), "tool_calls": []},
            {"content": json.dumps({"id": "scanner", "name": "扫描器", "start": "a", "stages": [{"id": "a", "name": "A", "goal": "g"}], "confidence": "low"}), "tool_calls": []},
            {"content": "[]", "tool_calls": []},
        ]),
    )
    r = client.post("/api/templates/generate", json={"description": "一个扫描器", "name": "扫描器"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    # 等待后台线程完成
    import time
    for _ in range(50):
        if server.generation_done(job_id):
            break
        time.sleep(0.05)
    with client.stream("GET", f"/api/templates/generate/{job_id}/events") as res:
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        body = "".join(res.iter_text())
    assert "complete" in body


def test_generation_requires_input():
    assert client.post("/api/templates/generate", json={}).status_code == 400


def test_conversation_crud():
    r = client.post("/api/conversations", json={"kind": "assistant", "name": "mgr-1", "template_id": server._LITE_PENTEST_TEMPLATE["id"]})
    assert r.status_code == 200
    conv = r.json()
    assert conv["kind"] == "assistant"
    cid = conv["id"]
    assert client.get("/api/conversations").json()["conversations"][0]["id"] == cid
    r = client.put(f"/api/conversations/{cid}", json={"name": "renamed"})
    assert r.json()["name"] == "renamed"
    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert client.get("/api/conversations").json()["conversations"] == []


def test_conversation_message_assistant(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_get_provider_for",
        lambda model="", effort="": _FakeProvider([{"content": "understood", "tool_calls": []}]),
    )
    cid = client.post("/api/conversations", json={"kind": "assistant", "name": "m", "template_id": server._LITE_PENTEST_TEMPLATE["id"]}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/messages", json={"message": "hello"})
    assert r.status_code == 200
    assert "content" in r.json()
    conv = next(c for c in client.get("/api/conversations").json()["conversations"] if c["id"] == cid)
    assert len(conv["messages"]) == 2


def test_providers_include_reasoning():
    providers = client.get("/api/providers").json()["providers"]
    assert providers["openai"]["reasoning"]["efforts"] == ["off", "low", "medium", "high"]
    assert providers["deepseek"]["reasoning"]["efforts"] == ["off", "low", "high", "max"]


def test_models_requires_key():
    assert client.get("/api/models").status_code == 400


def test_models_lists_from_provider(monkeypatch):
    rt._active().settings["api_key"] = "sk"
    monkeypatch.setattr(rt, "list_models", lambda base_url, api_key: [{"id": "m1", "reasoning_efforts": ["low", "high"]}])
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == ["m1"]
    assert body["efforts"] == ["low", "high"]


def test_conversation_stream(monkeypatch):
    rt._active().settings["api_key"] = "sk"

    class FakeProvider:
        def stream_chat(self, messages, tools):
            yield {"type": "delta", "content": "bye "}
            yield {"type": "delta", "content": "world"}
            yield {"type": "done", "content": "bye world", "tool_calls": []}

    monkeypatch.setattr(rt, "_get_provider_for", lambda model="", effort="": FakeProvider())
    cid = client.post("/api/conversations", json={"kind": "assistant", "name": "m", "template_id": server._LITE_PENTEST_TEMPLATE["id"]}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/messages/stream", json={"message": "hello"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    with client.stream("GET", f"/api/conversations/{cid}/messages/stream/{job_id}/events") as res:
        assert res.status_code == 200
        body = "".join(res.iter_text())
    assert "content_delta" in body
    assert "message_complete" in body
    conv = next(c for c in client.get("/api/conversations").json()["conversations"] if c["id"] == cid)
    assert conv["messages"][-1]["content"] == "bye world"


def test_run_self_check_records_evolution(monkeypatch):
    import time

    rt._active().settings["api_key"] = "sk"

    class FakeProvider:
        def __init__(self):
            self.i = 0

        def chat(self, messages, tools):
            self.i += 1
            if self.i == 1:
                return {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]}
            if self.i == 2:
                return {"content": "done", "tool_calls": []}
            if self.i == 3:
                return {"content": "# Report", "tool_calls": []}
            return {"content": '{"summary":"ok","steps":[],"suggestions":[],"unresolved":[],"confidence":"low"}', "tool_calls": []}

        def stream_chat(self, messages, tools):
            r = self.chat(messages, tools)
            content = r.get("content") or ""
            if content:
                yield {"type": "delta", "content": content}
            yield {"type": "done", "content": content, "tool_calls": r.get("tool_calls") or []}

    monkeypatch.setattr(rt, "_get_provider", lambda: FakeProvider())
    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    r = client.post("/api/runs", json={"template": tpl, "target": "example.com", "self_check": True})
    assert r.status_code == 200
    run_id = r.json()["id"]
    detail = None
    for _ in range(120):
        try:
            detail = client.get(f"/api/runs/{run_id}").json()
        except Exception:
            time.sleep(0.05)
            continue
        if detail is not None and any(e["type"] == "run_finished" for e in detail.get("events", [])):
            break
        time.sleep(0.05)
    assert detail is not None and detail.get("self_check") is True
    assert "summary" in (detail.get("evolution") or {})


def test_run_endpoint_returns_evolution(monkeypatch):
    rt._active().settings["api_key"] = "sk"

    class FakeProvider:
        def __init__(self):
            self.i = 0

        def chat(self, messages, tools):
            self.i += 1
            if self.i == 1:
                return {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]}
            if self.i == 2:
                return {"content": "done", "tool_calls": []}
            if self.i == 3:
                return {"content": "# Report", "tool_calls": []}
            return {"content": '{"summary":"ok","steps":[],"suggestions":[{"type":"other","where":"s","detail":"d"}],"unresolved":[],"confidence":"low"}', "tool_calls": []}

    monkeypatch.setattr(rt, "_get_provider", lambda: FakeProvider())
    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    r = client.post("/api/run", json={"template": tpl, "target": "example.com", "self_check": True})
    body = r.json()
    assert body.get("self_check") is True
    assert body.get("evolution", {}).get("suggestions")


def test_conversation_persists_self_check():
    cid = client.post("/api/conversations", json={"kind": "task", "name": "t"}).json()["id"]
    r = client.put(f"/api/conversations/{cid}", json={"self_check": True})
    assert r.json()["self_check"] is True
    assert client.get("/api/conversations").json()["conversations"][0]["self_check"] is True


def test_seeded_templates_initial_set():
    assert server._LITE_PENTEST_TEMPLATE["id"] == "builtin-full-pentest-lite"
    assert server._LITE_PENTEST_TEMPLATE["tools"]
    for stage in server._LITE_PENTEST_TEMPLATE["stages"]:
        for binding in stage.get("tools", []):
            assert binding["tool"] != "nuclei"


def test_lite_uses_builtin_only_tools():
    runners = {t["name"]: t["runner"] for t in server._LITE_PENTEST_TEMPLATE["tools"]}
    assert set(runners.values()) == {"builtin"}


def test_marketplace_lists_builtin_modules():
    from lattice_ai.builtin_templates import MATRIX_TEMPLATE_IDS

    r = client.get("/api/marketplace")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["templates"]}
    assert ids == set(MATRIX_TEMPLATE_IDS) | {"builtin-full-pentest-lite", "builtin-web-full"}


def test_install_lite_template_installs_directly():
    """The lite entry requires no external tools, so install saves the template
    and returns immediately without an install job."""
    r = client.post("/api/marketplace/builtin-full-pentest-lite/install")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "builtin-full-pentest-lite"
    assert "job_id" not in body
    assert client.get("/api/templates/builtin-full-pentest-lite").status_code == 200


def test_tools_list_is_truthful():
    r = client.get("/api/tools")
    assert r.status_code == 200
    tools = r.json()["tools"]
    by_name = {t["name"]: t for t in tools}
    dnsx = by_name["dnsx"]
    # registry tools report install state with a sim fallback guaranteed
    assert dnsx["status"] in ("installed", "missing")
    assert dnsx["tier_hint"] in ("real", "sim")
    assert dnsx["available"] is True
    for t in tools:
        if t["status"] == "unavailable":
            assert t["available"] is False


def test_agent_run_streams_content_delta(monkeypatch):
    from lattice_ai import agent as agent_mod
    from lattice_ai.models import from_dict, Template

    class FakeStream(agent_mod.WorkflowAgent):
        def __init__(self, provider, registry, event_log, approver=None, max_iterations=25, prior_context=None):
            self.provider = provider
            self.event_log = event_log

        def run(self, template, target, *, cwd=None):
            self.provider.chat([], [])
            self.event_log.append("agent_message", {"content": "hello", "tool_calls": []})
            return {}

    monkeypatch.setattr(rt, "WorkflowAgent", FakeStream)

    class P:
        def chat(self, messages, tools):
            return {"content": "hello", "tool_calls": []}

        def stream_chat(self, messages, tools):
            yield {"type": "delta", "content": "hello"}
            yield {"type": "done", "content": "hello", "tool_calls": []}

    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    parsed = from_dict(Template, tpl)
    sink = []
    rt._execute_run(parsed, P(), "example.com", True, event_sink=sink.append, self_check=False)
    assert any(e["type"] == "content_delta" for e in sink)


def test_models_accepts_provisional_credentials(monkeypatch):
    captured = {}

    def fake_list(base_url, api_key):
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        return [{"id": "gpt-5.1"}, {"id": "gpt-4o-mini"}]

    monkeypatch.setattr(rt, "list_models", fake_list)
    rt._active().settings["api_key"] = ""
    r = client.get("/api/models", params={"base_url": "https://api.openai.com/v1", "api_key": "sk-provisional"})
    assert r.status_code == 200
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["api_key"] == "sk-provisional"
    assert r.json()["provider"] == "openai"
    assert "gpt-5.1" in r.json()["models"]


def test_settings_redacts_api_key():
    rt._active().settings["api_key"] = "sk-test-secret"
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["api_key"] == ""
    assert body["has_api_key"] is True
    assert "sk-test-secret" not in r.text


def test_current_project_redacts_api_key():
    rt._active().settings["api_key"] = "sk-test-secret"
    r = client.get("/api/projects/current")
    assert r.status_code == 200
    assert "sk-test-secret" not in r.text
    assert r.json()["settings"]["has_api_key"] is True


def test_put_settings_rejects_non_string():
    r = client.put("/api/settings", json={"base_url": 123, "model": 123})
    assert r.status_code == 422


def test_preferences_endpoints(isolated_store, tmp_path, monkeypatch):
    # isolate the real data/preferences.json: this endpoint writes the file
    monkeypatch.setattr(preferences, "_PREFS_FILE", tmp_path / "preferences.json")
    r = client.put("/api/preferences", json={"theme": "dark"})
    assert r.status_code == 200
    assert r.json() == {"theme": "dark", "language": "en"}
    assert client.get("/api/preferences").json() == {"theme": "dark", "language": "en"}


def test_preferences_invalid_theme_422(isolated_store):
    r = client.put("/api/preferences", json={"theme": "neon"})
    assert r.status_code == 422


def test_toolchain_scan(isolated_store, monkeypatch):
    monkeypatch.setattr(rt, "find_executable", lambda name: "/usr/bin/" + name if name == "nuclei" else None)
    r = client.get("/api/toolchain")
    assert r.status_code == 200
    tools = {t["name"]: t for t in r.json()["tools"]}
    assert tools["nuclei"]["available"] is True
    assert tools["sqlmap"]["available"] is False


def test_toolchain_install_kicks_job(isolated_store, monkeypatch):
    monkeypatch.setattr(rt, "install_toolchain", lambda names, **kw: [{"name": n, "status": "installed"} for n in names])
    r = client.post("/api/toolchain/install", json={"tools": ["nuclei"]})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "installing"
    assert body["job_id"]


def test_toolchain_install_status(isolated_store):
    server._install_jobs["job1"] = {
        "job_id": "job1",
        "status": "done",
        "results": [{"name": "nuclei", "status": "installed"}],
        "error": None,
    }
    r = client.get("/api/toolchain/install/job1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["tools_installed"]["nuclei"] is True


def test_put_settings_stores_reasoning_effort(isolated_store):
    r = client.put("/api/settings", json={"provider": "deepseek", "reasoning_effort": "high"})
    assert r.status_code == 200
    assert r.json()["reasoning_effort"] == "high"
    assert rt._active().settings["reasoning_effort"] == "high"


def test_run_persists_findings(monkeypatch):
    import time

    monkeypatch.setattr(
        rt,
        "generate_findings",
        lambda provider, facts, template, target, known_false_positives=None: [{
            "title": "Exposed .env",
            "severity": "high",
            "status": "confirmed",
            "cwe": "CWE-538",
            "cvss": "7.5",
            "target": target,
            "confidence": "medium",
            "summary": "s",
            "impact": "i",
            "remediation": "r",
        }],
    )
    monkeypatch.setattr(
        rt,
        "_get_provider",
        lambda: _FakeProvider([
            {"content": None, "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}]},
            {"content": "done", "tool_calls": []},
            {"content": "# Report", "tool_calls": []},
        ]),
    )
    tpl = {
        "id": "t1", "name": "demo", "start": "a",
        "stages": [{"id": "a", "name": "a", "tools": [{"tool": "echo", "key": "out", "defaults": {"msg": "hi"}}]}],
        "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}],
    }
    started = client.post("/api/runs", json={"template": tpl, "target": "example.com"})
    assert started.status_code == 200
    run_id = started.json()["id"]
    for _ in range(200):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail.get("report") is not None:
            break
        time.sleep(0.05)
    findings = client.get("/api/findings").json()["findings"]
    assert any(f["title"] == "Exposed .env" for f in findings)


def test_clone_template_unique_id():
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    client.put("/api/templates/t1", json=tpl)
    r1 = client.post("/api/templates/t1/clone").json()["id"]
    r2 = client.post("/api/templates/t1/clone").json()["id"]
    assert r1 != r2


def test_put_template_rejects_id_mismatch():
    tpl = {"id": "other", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    assert client.put("/api/templates/t1", json=tpl).status_code == 400


def test_update_skill_rejects_name_mismatch():
    client.post("/api/skills", json={"name": "recon", "content": "# x"})
    r = client.put("/api/skills/recon", json={"name": "other", "content": "# x"})
    assert r.status_code == 400


def test_non_string_names_rejected():
    assert client.post("/api/skills", json={"name": 123, "content": "# x"}).status_code == 422
    project_id = client.get("/api/projects").json()["current"]
    assert client.post(f"/api/projects/{project_id}/rename", json={"name": 123}).status_code == 422
    tpl = {"id": "t1", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}
    client.put("/api/templates/t1", json=tpl)
    assert client.post("/api/templates/t1/rename", json={"name": 123}).status_code == 422


def test_seed_does_not_resurrect_trashed_builtin(tmp_path, monkeypatch):
    from lattice_ai import server
    from lattice_ai.library import TemplateStore

    store = TemplateStore(tmp_path / "templates")
    store.save("builtin-info-gathering", {"id": "builtin-info-gathering", "name": "x"})
    store.delete("builtin-info-gathering")
    monkeypatch.setattr(rt, "_template_store", store)
    server._seed_global_assets()
    assert store.get("builtin-info-gathering") is None


def test_approval_api_create_and_resolve():
    r = client.post("/api/approvals", json={"tool": "scan_port", "args": {"target": "example.com"}})
    assert r.status_code == 200
    approval_id = r.json()["approval_id"]
    resolved = client.post(f"/api/approvals/{approval_id}/resolve", json={"approved": True, "reason": "ok"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "approved"


def test_approval_api_missing_returns_404():
    assert client.post("/api/approvals/missing/resolve", json={"approved": True}).status_code == 404


def test_import_mcp_discovers_sample_tools():
    source = f"{sys.executable} -m lattice_ai.sample_mcp"
    r = client.post("/api/tools/import-mcp", json={"source": source})
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    assert "scan_port" in names


def test_purge_and_empty_trash_api():
    rt._tool_store.save("tmp-tool", {"name": "tmp-tool", "description": "d", "runner": "cli", "command": ["echo"]})
    rt._tool_store.delete("tmp-tool")
    assert rt._tool_store.trash_list()
    assert client.delete("/api/trash/tools/tmp-tool").status_code == 200
    assert not rt._tool_store.trash_list()

    rt._tool_store.save("tmp-tool-2", {"name": "tmp-tool-2", "description": "d", "runner": "cli", "command": ["echo"]})
    rt._tool_store.delete("tmp-tool-2")
    assert client.delete("/api/trash", params={"kind": "tools"}).status_code == 200
    assert not rt._tool_store.trash_list()


def test_tools_list_includes_capability_and_usage():
    r = client.get("/api/tools")
    assert r.status_code == 200
    tools = r.json()["tools"]
    nmap = next((t for t in tools if t["name"] == "nmap"), None)
    assert nmap is not None
    assert nmap["capability"] == "recon"
    # nmap is a registry cli tool now; its usage hint follows the runner
    assert nmap["usage"] in ("builtin", "cli")
