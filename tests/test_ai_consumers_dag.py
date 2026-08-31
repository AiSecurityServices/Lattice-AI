import json

from lattice_ai import review
from lattice_ai.analyzer import ProjectModel
from lattice_ai.generator import generate_template
from lattice_ai.improve import apply_suggestion
from lattice_ai.models import Stage, Template


class _Provider:
    def __init__(self, content):
        self.content = content

    def chat(self, messages, tools):
        return {"content": self.content, "tool_calls": []}


def test_review_prompt_is_dag_aligned():
    assert "back-edge" not in review._PROMPT
    assert "transition" not in review._PROMPT
    assert "depends_on" in review._PROMPT


def test_generate_template_outputs_depends_on():
    payload = {
        "id": "gen-1",
        "name": "生成流程",
        "start": "a",
        "stages": [
            {"id": "a", "name": "A", "depends_on": []},
            {"id": "b", "name": "B", "depends_on": ["a"]},
        ],
        "issues": [],
        "confidence": "low",
    }
    provider = _Provider(json.dumps(payload, ensure_ascii=False))
    model = ProjectModel(summary="扫描", entrypoints=[], capabilities=[], dependencies=[], confidence="low")
    template, report = generate_template(provider, model, [], [])
    preview = report["template_preview"]
    assert "transitions" not in preview
    assert preview["stages"][0]["depends_on"] == []
    assert preview["stages"][1]["depends_on"] == ["a"]
    assert template.stages[1].depends_on == ["a"]


def test_apply_suggestion_add_depends_on():
    t = Template(id="t", name="n", start="a", stages=[
        Stage(id="a", name="A"),
        Stage(id="b", name="B"),
    ])
    updated = apply_suggestion(t, {"type": "add_depends_on", "stage_id": "b", "depends_on": "a"})
    assert updated.stages[1].depends_on == ["a"]
