from copy import deepcopy
import re

from lattice_ai.graph import validate_template
from lattice_ai.models import GateRule, Stage, Template, Tool, ToolBinding


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "stage"


def apply_suggestion(template: Template, suggestion: dict) -> Template:
    result = deepcopy(template)
    kind = suggestion.get("type")
    if kind == "add_tool":
        stage = next((s for s in result.stages if s.id == suggestion.get("stage_id")), None)
        if stage is None:
            raise ValueError(f"stage not found: {suggestion.get('stage_id')}")
        tool_name = suggestion.get("tool_name")
        if not tool_name:
            raise ValueError("add_tool requires tool_name")
        if not any(t.name == tool_name for t in result.tools):
            result.tools.append(Tool(name=tool_name))
        if not any(b.tool == tool_name for b in stage.tools):
            stage.tools.append(ToolBinding(tool=tool_name))
        return _validated(result, kind)
    if kind == "remove_tool":
        stage = next((s for s in result.stages if s.id == suggestion.get("stage_id")), None)
        if stage is None:
            raise ValueError(f"stage not found: {suggestion.get('stage_id')}")
        tool_name = suggestion.get("tool_name")
        stage.tools = [b for b in stage.tools if b.tool != tool_name]
        return _validated(result, kind)
    if kind == "add_stage":
        stage_name = str(suggestion.get("stage_name") or "stage")
        stage_id = _slug(stage_name)
        existing = {s.id for s in result.stages}
        base = stage_id
        index = 2
        while stage_id in existing:
            stage_id = f"{base}-{index}"
            index += 1
        depends_on = suggestion.get("depends_on") or []
        after = suggestion.get("after_stage_id")
        if after:
            depends_on = [after] + [d for d in depends_on if d != after]
        stage = Stage(id=stage_id, name=stage_name, depends_on=list(depends_on))
        result.stages.append(stage)
        return _validated(result, kind)
    if kind == "remove_stage":
        stage_id = suggestion.get("stage_id")
        if stage_id == result.start:
            raise ValueError("cannot remove the start stage")
        if not any(s.id == stage_id for s in result.stages):
            raise ValueError(f"stage not found: {stage_id}")
        result.stages = [s for s in result.stages if s.id != stage_id]
        for s in result.stages:
            s.depends_on = [d for d in s.depends_on if d != stage_id]
        return _validated(result, kind)
    if kind == "add_depends_on":
        stage = _stage_or_raise(result, suggestion.get("stage_id"))
        dep = suggestion.get("depends_on")
        if not dep:
            raise ValueError("add_depends_on requires depends_on")
        if dep not in stage.depends_on:
            stage.depends_on.append(dep)
        return _validated(result, kind)
    if kind == "remove_depends_on":
        stage = _stage_or_raise(result, suggestion.get("stage_id"))
        dep = suggestion.get("depends_on")
        if dep in stage.depends_on:
            stage.depends_on.remove(dep)
        return _validated(result, kind)
    if kind == "set_condition":
        stage = _stage_or_raise(result, suggestion.get("stage_id"))
        stage.condition = suggestion.get("condition")
        return _validated(result, kind)
    if kind == "set_optional":
        stage = _stage_or_raise(result, suggestion.get("stage_id"))
        stage.optional = bool(suggestion.get("optional"))
        return _validated(result, kind)
    if kind == "add_gate":
        stage = _stage_or_raise(result, suggestion.get("stage_id"))
        name = str(suggestion.get("name") or "gate")
        if any(g.name == name for g in stage.gates):
            return result
        stage.gates.append(GateRule(
            name=name,
            check=suggestion.get("check") or {},
            on_fail=str(suggestion.get("on_fail") or "block"),
        ))
        return _validated(result, kind)
    if kind == "remove_gate":
        stage = _stage_or_raise(result, suggestion.get("stage_id"))
        name = suggestion.get("name")
        stage.gates = [g for g in stage.gates if g.name != name]
        return _validated(result, kind)
    raise ValueError(f"unsupported suggestion type: {kind}")


def _stage_or_raise(template: Template, stage_id) -> Stage:
    stage = next((s for s in template.stages if s.id == stage_id), None)
    if stage is None:
        raise ValueError(f"stage not found: {stage_id}")
    return stage


def _validated(template: Template, kind: str) -> Template:
    try:
        validate_template(template)
    except Exception as exc:
        raise ValueError(f"invalid template after {kind}: {exc}") from exc
    return template
