from types import SimpleNamespace

from lattice_ai.assistant import AssistantAgent, fetch_source, generate_asset_draft
from lattice_ai.events import EventLog
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.workspace import ProjectStore


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


def _env(tmp_path, **seeds):
    store = ProjectStore(
        tmp_path / "projects",
        seed_settings={"provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": "sk"},
    )
    template_store = TemplateStore(tmp_path / "templates")
    tool_store = ToolStore(tmp_path / "tools")
    skill_store = SkillStore(tmp_path / "skills")
    for tid, data in seeds.get("seed_templates", {}).items():
        template_store.save(tid, data)
    for name, data in seeds.get("seed_skills", {}).items():
        skill_store.save(name, data)
    for recipe in seeds.get("seed_recipes", []):
        tool_store.save(recipe["name"], recipe)
    return SimpleNamespace(
        store=store,
        template_store=template_store,
        tool_store=tool_store,
        skill_store=skill_store,
    )


def _agent(provider, env, log):
    return AssistantAgent(
        provider,
        env.store,
        log,
        template_store=env.template_store,
        tool_store=env.tool_store,
        skill_store=env.skill_store,
    )


def test_fetch_source_local_file(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text("# Recon\n1. enumerate", encoding="utf-8")
    content, hint = fetch_source(str(skill))
    assert hint == "skill"
    assert "enumerate" in content


def test_fetch_source_local_dir(tmp_path):
    d = tmp_path / "myskill"
    d.mkdir()
    (d / "SKILL.md").write_text("# X\n- y", encoding="utf-8")
    content, hint = fetch_source(str(d))
    assert hint == "skill"
    assert "y" in content


def test_generate_asset_draft():
    provider = FakeProvider([{"content": '{"type":"skill","data":{"name":"recon","description":"d","category":"","tags":[],"content":"# R"}}', "tool_calls": []}])
    draft = generate_asset_draft(provider, "https://x", "# R", "skill")
    assert draft["type"] == "skill"
    assert draft["data"]["name"] == "recon"


def test_assistant_imports_skill_requires_confirmation(tmp_path, monkeypatch):
    env = _env(tmp_path)
    monkeypatch.setattr("lattice_ai.assistant.fetch_source", lambda source: ("# Recon\n1. enumerate", "skill"))
    monkeypatch.setattr(
        "lattice_ai.assistant.generate_asset_draft",
        lambda provider, source, content, hint: {"type": "skill", "data": {"name": "recon-x", "description": "d", "category": "", "tags": [], "content": "# Recon"}},
    )
    provider = FakeProvider([
        {"content": "我的理解...", "tool_calls": [{"id": "c1", "name": "import_asset", "arguments": {"source": "https://github.com/a/b"}}]},
        {"content": "done", "tool_calls": []},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    result = _agent(provider, env, log).respond("import this skill")
    assert result.get("pending") == {"tool": "import_asset", "args": {"source": "https://github.com/a/b"}}
    assert not any(s["name"] == "recon-x" for s in env.skill_store.list())

    confirmed = _agent(provider, env, log).respond("确认", confirm=result["pending"])
    assert any(s["name"] == "recon-x" for s in env.skill_store.list())


def test_assistant_lists_templates(tmp_path):
    env = _env(tmp_path, seed_templates={"demo": {"id": "demo", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}})
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "list_templates", "arguments": {}}]},
        {"content": "done", "tool_calls": []},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    _agent(provider, env, log).respond("list templates")
    results = [e.data.get("result") for e in log.read() if e.type == "tool_result"]
    assert any("demo" in str(r) for r in results)


def test_assistant_pending_for_destructive_tool(tmp_path):
    env = _env(tmp_path, seed_recipes=[{"name": "nmap", "description": "scan", "runner": "cli", "command": ["nmap", "{target}"], "parameters": {}}])
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "delete_tool", "arguments": {"name": "nmap"}}]},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    result = _agent(provider, env, log).respond("删除 nmap")
    assert result.get("pending") == {"tool": "delete_tool", "args": {"name": "nmap"}}
    assert any(t["name"] == "nmap" for t in env.tool_store.list())


def test_assistant_confirms_destructive_tool(tmp_path):
    env = _env(tmp_path, seed_recipes=[{"name": "nmap", "description": "scan", "runner": "cli", "command": ["nmap", "{target}"], "parameters": {}}])
    provider = FakeProvider([
        {"content": "deleted", "tool_calls": []},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    result = _agent(provider, env, log).respond("确认", confirm={"tool": "delete_tool", "args": {"name": "nmap"}})
    assert result.get("pending") is None
    assert not any(t["name"] == "nmap" for t in env.tool_store.list())


def test_assistant_get_template(tmp_path):
    env = _env(
        tmp_path,
        seed_templates={
            "demo": {
                "id": "demo",
                "name": "demo",
                "start": "a",
                "stages": [{"id": "a", "name": "a", "goal": "scan"}],
                "tools": [],
            }
        },
    )
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "get_template", "arguments": {"template_id": "demo"}}]},
        {"content": "got", "tool_calls": []},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    _agent(provider, env, log).respond("show demo")
    results = [e.data.get("result") for e in log.read() if e.type == "tool_result"]
    assert any("demo" in str(r) for r in results)


def test_assistant_save_template_requires_confirmation(tmp_path):
    env = _env(tmp_path)
    template = {
        "id": "gen",
        "name": "Generated",
        "start": "s1",
        "stages": [{"id": "s1", "name": "Scan", "goal": "scan"}],
        "tools": [],
        "skills": [],
    }
    provider = FakeProvider([
        {"content": "plan", "tool_calls": [{"id": "c1", "name": "save_template", "arguments": {"template_id": "gen", "template": template}}]},
        {"content": "saved", "tool_calls": []},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    result = _agent(provider, env, log).respond("save generated template")
    assert result.get("pending") == {"tool": "save_template", "args": {"template_id": "gen", "template": template}}
    assert not any(t["id"] == "gen" for t in env.template_store.list())

    confirmed = _agent(provider, env, log).respond("确认", confirm=result["pending"])
    assert any(t["id"] == "gen" for t in env.template_store.list())


def test_assistant_generate_template_from_source(tmp_path, monkeypatch):
    env = _env(tmp_path)
    monkeypatch.setattr("lattice_ai.assistant.fetch_source", lambda source: ("# Project", "tool"))
    monkeypatch.setattr(
        "lattice_ai.assistant.generate_template_draft",
        lambda provider, source, content, hint: {
            "id": "draft",
            "name": "Draft",
            "start": "s1",
            "stages": [{"id": "s1", "name": "Scan", "goal": "scan"}],
            "tools": [],
            "skills": [],
        },
    )
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "generate_template_from_source", "arguments": {"source": "https://github.com/a/b"}}]},
        {"content": None, "tool_calls": [{"id": "c2", "name": "save_template", "arguments": {"template_id": "draft", "template": {"id": "draft", "name": "Draft", "start": "s1", "stages": [{"id": "s1", "name": "Scan", "goal": "scan"}], "tools": [], "skills": []}}}]},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    result = _agent(provider, env, log).respond("make template from project")
    assert result.get("pending") is not None
    assert result["pending"]["tool"] == "save_template"


def test_assistant_merges_template_tools(tmp_path):
    from lattice_ai.models import Template, from_dict

    env = _env(tmp_path, seed_templates={
        "t1": {"id": "t1", "name": "T", "start": "a", "stages": [{"id": "a", "name": "a"}],
               "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}]},
    })
    log = EventLog(tmp_path / "s.jsonl")
    provider = FakeProvider([{"content": "ok", "tool_calls": []}])
    template = from_dict(Template, env.template_store.get("t1"))
    agent = AssistantAgent(
        provider, env.store, log,
        template_store=env.template_store,
        tool_store=env.tool_store,
        skill_store=env.skill_store,
        template=template,
    )
    specs = agent._tool_specs()
    names = {s["function"]["name"] for s in specs}
    assert "echo" in names
    assert "run_workflow" in names
    assert "list_templates" in names


def test_assistant_template_tool_specs_have_no_duplicate_names(tmp_path):
    from lattice_ai.models import Template, from_dict

    env = _env(tmp_path, seed_templates={
        "t1": {"id": "t1", "name": "T", "start": "a", "stages": [{"id": "a", "name": "a"}],
               "tools": [{"name": "echo", "description": "echo", "runner": "builtin"}]},
    })
    log = EventLog(tmp_path / "s.jsonl")
    provider = FakeProvider([{"content": "ok", "tool_calls": []}])
    template = from_dict(Template, env.template_store.get("t1"))
    agent = AssistantAgent(
        provider, env.store, log,
        template_store=env.template_store,
        tool_store=env.tool_store,
        skill_store=env.skill_store,
        template=template,
    )
    names = [s["function"]["name"] for s in agent._tool_specs()]
    assert len(names) == len(set(names))


def test_assistant_bind_tool_confirmation(tmp_path):
    env = _env(
        tmp_path,
        seed_recipes=[{"name": "nmap", "description": "port scan", "runner": "cli", "command": ["nmap", "{target}"], "parameters": {}}],
        seed_templates={"demo": {"id": "demo", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}},
    )
    provider = FakeProvider([
        {"content": None, "tool_calls": [{"id": "c1", "name": "bind_tool", "arguments": {"tool": "nmap", "template_id": "demo"}}]},
    ])
    log = EventLog(tmp_path / "s.jsonl")
    result = _agent(provider, env, log).respond("bind nmap")
    assert result.get("pending") == {"tool": "bind_tool", "args": {"tool": "nmap", "template_id": "demo"}}
    confirmed = _agent(FakeProvider([{"content": "ok", "tool_calls": []}]), env, log).respond("确认", confirm=result["pending"])
    template = env.template_store.get("demo")
    assert any(t["name"] == "nmap" for t in template["tools"])
    assert any(b["tool"] == "nmap" for b in template["stages"][0]["tools"])


def test_assistant_try_tool_executes_and_returns_report(tmp_path, monkeypatch):
    env = _env(tmp_path, seed_recipes=[{"name": "nmap", "description": "port scan", "runner": "cli", "command": ["nmap", "{target}"], "parameters": {}}])
    monkeypatch.setattr("lattice_ai.assistant.map_target_to_args", lambda provider, tool, target: {"target": target})
    monkeypatch.setattr("lattice_ai.assistant.generate_findings", lambda provider, facts, template, target="": [{"id": "f1", "title": "open", "severity": "low"}])
    monkeypatch.setattr("lattice_ai.assistant.generate_report", lambda provider, facts, template: "# report")
    provider = FakeProvider([{"content": "ok", "tool_calls": []}])
    log = EventLog(tmp_path / "s.jsonl")
    agent = _agent(provider, env, log)
    result = agent._execute("try_tool", {"tool": "nmap", "target": "example.com"})
    assert result["tool"] == "nmap"
    assert result["report"] == "# report"
    assert result["findings"][0]["id"] == "f1"


def test_assistant_apply_workflow_suggestion(tmp_path):
    env = _env(
        tmp_path,
        seed_templates={"demo": {"id": "demo", "name": "demo", "start": "a", "stages": [{"id": "a", "name": "a"}], "tools": []}},
    )
    agent = _agent(FakeProvider([{"content": "ok", "tool_calls": []}]), env, EventLog(tmp_path / "s.jsonl"))
    result = agent._execute("apply_workflow_suggestion", {
        "template_id": "demo",
        "suggestion": {"type": "add_stage", "stage_name": "new", "after_stage_id": "a"},
    })
    assert "new" in result["stages"]
    template = env.template_store.get("demo")
    assert any(s["id"] == "new" for s in template["stages"])
