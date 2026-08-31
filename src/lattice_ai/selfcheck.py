import json


def _extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _extract_json_list(text):
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def group_units(events, autonomous=False):
    """Segment run events into execution units for self-checking.

    Controlled runs: one unit per stage (stage_started..stage_finished).
    Autonomous runs: one unit per agent_message plus its tool calls/results.
    Returns a list of {"label", "agent_message", "tool_calls", "tool_results"}.
    """
    units = []
    current = None

    def close():
        nonlocal current
        if current is not None:
            units.append(current)
            current = None

    for ev in events:
        etype = ev.get("type")
        if etype == "stage_started" and not autonomous and current is None:
            current = {"label": f"stage {ev.get('data', {}).get('stage', '?')}", "agent_message": "", "tool_calls": [], "tool_results": []}
            continue
        if etype == "agent_message" and autonomous:
            close()
            current = {
                "label": f"step {len(units) + 1}",
                "agent_message": (ev.get("data") or {}).get("content", ""),
                "tool_calls": [],
                "tool_results": [],
            }
            continue
        if etype == "stage_finished" and not autonomous:
            close()
            continue
        if current is not None:
            if etype == "tool_call":
                current["tool_calls"].append((ev.get("data") or {}).get("tool"))
            elif etype == "tool_result":
                current["tool_results"].append((ev.get("data") or {}).get("result"))
    close()
    return units


def self_check_unit(provider, unit):
    """Reflect on one execution unit and return a list of {kind, text} notes."""
    prompt = (
        "You are a workflow quality reviewer. Given one execution unit, identify: "
        "difficulties (difficulty), conflicts with the workflow description or stage conditions (conflict), "
        "ambiguities or misunderstandings (misunderstanding), and optimization opportunities (opportunity). "
        "Output ONLY a JSON array of {kind, text}.\n"
        "text 字段请用简体中文输出。\n\n"
        f"Unit: {unit.get('label')}\nAgent reasoning: {unit.get('agent_message') or 'none'}\n"
        f"Tool calls: {unit.get('tool_calls')}\nTool results: {unit.get('tool_results')}"
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    text = (response.get("content") or "").strip()
    data = _extract_json_list(text)
    return data if isinstance(data, list) else []


def evolution_report(provider, template, events, unit_notes, fp_stats=None):
    """Aggregate run feedback into a structured evolution report."""
    name = template.get("name", "") if isinstance(template, dict) else getattr(template, "name", "")
    prompt = (
        "You are a workflow improvement analyst. Review the run events and per-unit self-check notes below. "
        "Output ONLY a JSON object with keys: summary (str), steps (list of {label, difficulties, conflicts, misunderstandings}), "
        "suggestions (list of machine-executable objects; type in add_tool|remove_tool|add_stage|remove_stage|add_depends_on|remove_depends_on|set_condition|set_optional|add_gate|remove_gate|other). "
        "Use these fields by type: "
        "add_tool: stage_id, tool_name, detail; "
        "remove_tool: stage_id, tool_name, detail; "
        "add_stage: stage_name, after_stage_id, detail; "
        "remove_stage: stage_id, detail; "
        "add_depends_on: stage_id, depends_on, detail; "
        "remove_depends_on: stage_id, depends_on, detail; "
        "set_condition: stage_id, condition, detail; "
        "set_optional: stage_id, optional, detail; "
        "add_gate: stage_id, name, check, on_fail, detail; "
        "remove_gate: stage_id, name, detail; "
        "other: detail only. "
        "unresolved (list of str), confidence (high|medium|low).\n\n"
        "summary、steps、suggestions、unresolved 及 detail 等文本请用简体中文输出，JSON 键保持英文。\n\n"
        f"Template: {name}\nEvents: {json.dumps(events, ensure_ascii=False, default=str)}\n"
        f"Notes: {json.dumps(unit_notes, ensure_ascii=False, default=str)}"
    )
    if fp_stats:
        prompt += (
            "\nFalse-positive statistics from prior runs:\n" +
            json.dumps(fp_stats, ensure_ascii=False) +
            "\nUse these to propose add_gate / set_condition suggestions that tighten detection."
        )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    data = _extract_json((response.get("content") or "").strip())
    if not isinstance(data, dict):
        return {"summary": "", "steps": [], "suggestions": [], "unresolved": [], "confidence": "low"}
    return {
        "summary": data.get("summary", ""),
        "steps": data.get("steps", []),
        "suggestions": data.get("suggestions", []),
        "unresolved": data.get("unresolved", []),
        "confidence": data.get("confidence", "low"),
    }
