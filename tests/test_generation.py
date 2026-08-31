import json

from lattice_ai.analyzer import ProjectModel, analyze_project
from lattice_ai.resolver import ProjectFile, ProjectSnapshot


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, tools):
        return self.responses.pop(0)


def test_analyze_project_synthesizes_model():
    provider = _FakeProvider([
        {"content": '{"files_to_read": ["src/main.py"]}', "tool_calls": []},
        {"content": json.dumps({
            "summary": "a scanner",
            "entrypoints": ["src/main.py"],
            "tools": [{"name": "scan", "type": "cli", "command": ["scan", "{target}"], "parameters": {"type": "object", "properties": {"target": {"type": "string"}}}}],
            "skills": [],
            "capabilities": ["scan"],
            "dependencies": [],
            "confidence": "medium",
            "gaps": ["unknown auth"],
        }), "tool_calls": []},
    ])
    snap = ProjectSnapshot("/repo", [ProjectFile("src/main.py", 100, "source")])
    model = analyze_project(provider, snap, read_file=lambda path: "def main(): pass", budget=10)
    assert isinstance(model, ProjectModel)
    assert model.summary == "a scanner"
    assert model.tools[0]["name"] == "scan"
    assert model.confidence == "medium"
    assert model.gaps == ["unknown auth"]


def test_analyze_project_empty_snapshot():
    provider = _FakeProvider([])
    model = analyze_project(provider, ProjectSnapshot("/repo", []))
    assert model.confidence == "low"
    assert "无来源" in model.summary


def test_generate_template_and_report():
    from lattice_ai.generator import generate_template
    from lattice_ai.models import Skill, Tool

    provider = _FakeProvider([
        {"content": json.dumps({
            "id": "artex-like",
            "name": "ArtEx 流程",
            "start": "recon",
            "stages": [
                {"id": "recon", "name": "侦察", "goal": "发现资产", "tools": [{"tool": "scan", "key": "scan", "defaults": {}}], "skills": [{"skill": "sdk_fn"}]},
                {"id": "report", "name": "报告", "goal": "汇总"},
            ],
            "transitions": [{"id": "e1", "source": "recon", "target": "report", "description": "完成"}],
            "issues": [{"severity": "warning", "where": "sdk_fn", "message": "SDK 内部功能，缺可执行入口", "resolution": "作为 Skill 绑定"}],
            "confidence": "medium",
        }), "tool_calls": []},
    ])
    model = ProjectModel(summary="artex-like", confidence="medium")
    tools = [Tool(name="scan", runner="cli", command=["scan", "{target}"])]
    skills = [Skill(name="sdk_fn", content="# x")]
    template, report = generate_template(provider, model, tools, skills, "ArtEx 流程")
    assert template.stages[0].id == "recon"
    assert template.stages[0].skills[0].skill == "sdk_fn"
    assert report["confidence"] == "medium"
    assert any(iss["where"] == "sdk_fn" for iss in report["issues"])


def test_generation_job_description_mode(monkeypatch):
    import time
    import lattice_ai.generation as gen

    class FakeProvider:
        def __init__(self):
            self.n = 0

        def chat(self, messages, tools):
            self.n += 1
            if self.n == 1:
                return {"content": json.dumps({"summary": "扫描器", "tools": [], "skills": [], "capabilities": [], "dependencies": [], "confidence": "low"}), "tool_calls": []}
            if self.n == 2:
                return {"content": json.dumps({
                    "id": "scanner",
                    "name": "扫描器",
                    "start": "a",
                    "stages": [{"id": "a", "name": "A", "goal": "g"}],
                    "transitions": [],
                    "confidence": "low",
                }), "tool_calls": []}
            return {"content": "[]", "tool_calls": []}

    monkeypatch.setattr(gen, "get_provider", lambda: FakeProvider())
    job_id = gen.start_generation({"description": "一个扫描器", "name": "扫描器"})
    assert job_id
    for _ in range(50):
        if gen.generation_done(job_id):
            break
        time.sleep(0.05)
    events = gen.list_generation_events(job_id)
    assert any(e["type"] == "complete" for e in events)
    result = gen.generation_result(job_id)
    assert result["template"]["name"] == "扫描器"
    assert result["template"]["stages"][0]["id"] == "a"
    assert result["report"]["imports"]["tools"] == []
