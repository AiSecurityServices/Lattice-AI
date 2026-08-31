import pytest

from lattice_ai.improve import apply_suggestion
from lattice_ai.models import GateRule, Stage, Template, Tool, ToolBinding


def _template():
    return Template(
        id="t",
        name="t",
        start="a",
        stages=[
            Stage(id="a", name="a"),
            Stage(id="b", name="b", depends_on=["a"]),
        ],
    )


def test_add_tool_suggestion():
    t = apply_suggestion(_template(), {"type": "add_tool", "stage_id": "a", "tool_name": "nmap"})
    assert any(tool.name == "nmap" for tool in t.tools)
    assert any(b.tool == "nmap" for b in t.stages[0].tools)


def test_remove_tool_suggestion():
    t = apply_suggestion(
        _template(),
        {"type": "add_tool", "stage_id": "a", "tool_name": "nmap"},
    )
    t = apply_suggestion(t, {"type": "remove_tool", "stage_id": "a", "tool_name": "nmap"})
    assert all(b.tool != "nmap" for b in t.stages[0].tools)


def test_add_stage_suggestion_wires_depends_on():
    t = apply_suggestion(_template(), {"type": "add_stage", "stage_name": "new", "after_stage_id": "a"})
    stage = next(s for s in t.stages if s.id == "new")
    assert stage.depends_on == ["a"]


def test_add_stage_slugifies_name():
    t = apply_suggestion(_template(), {"type": "add_stage", "stage_name": "New Stage", "after_stage_id": "a"})
    assert any(s.id == "new-stage" for s in t.stages)


def test_remove_stage_suggestion():
    t = apply_suggestion(_template(), {"type": "remove_stage", "stage_id": "b"})
    assert all(s.id != "b" for s in t.stages)
    assert all("b" not in s.depends_on for s in t.stages)


def test_remove_start_stage_raises():
    with pytest.raises(ValueError):
        apply_suggestion(_template(), {"type": "remove_stage", "stage_id": "a"})


def test_remove_missing_stage_raises():
    with pytest.raises(ValueError):
        apply_suggestion(_template(), {"type": "remove_stage", "stage_id": "missing"})


def test_add_and_remove_depends_on():
    t = apply_suggestion(
        Template(id="t", name="t", start="a", stages=[
            Stage(id="a", name="a"),
            Stage(id="b", name="b"),
            Stage(id="c", name="c"),
        ]),
        {"type": "add_depends_on", "stage_id": "b", "depends_on": "a"},
    )
    assert "a" in t.stages[1].depends_on
    t = apply_suggestion(t, {"type": "remove_depends_on", "stage_id": "b", "depends_on": "a"})
    assert "a" not in t.stages[1].depends_on


def test_add_depends_on_creating_cycle_raises():
    t = _template()
    with pytest.raises(ValueError):
        apply_suggestion(t, {"type": "add_depends_on", "stage_id": "a", "depends_on": "b"})


def test_set_condition_and_optional():
    t = apply_suggestion(_template(), {"type": "set_condition", "stage_id": "b", "condition": {"op": "truthy", "key": "go"}})
    assert t.stages[1].condition == {"op": "truthy", "key": "go"}
    t = apply_suggestion(_template(), {"type": "set_optional", "stage_id": "b", "optional": True})
    assert t.stages[1].optional is True


def test_add_and_remove_gate():
    t = apply_suggestion(
        _template(),
        {"type": "add_gate", "stage_id": "b", "name": "has_data", "check": {"op": "truthy", "key": "b.data"}, "on_fail": "warn"},
    )
    assert t.stages[1].gates[0].name == "has_data"
    assert t.stages[1].gates[0].on_fail == "warn"
    t = apply_suggestion(t, {"type": "remove_gate", "stage_id": "b", "name": "has_data"})
    assert t.stages[1].gates == []


def test_unsupported_suggestion_raises():
    with pytest.raises(ValueError):
        apply_suggestion(_template(), {"type": "other"})
