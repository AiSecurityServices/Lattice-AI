from lattice_ai.selfcheck import evolution_report, group_units, self_check_unit


def test_group_units_controlled_by_stage():
    events = [
        {"type": "stage_started", "data": {"stage": "s1"}},
        {"type": "tool_call", "data": {"tool": "dnsx", "stage": "s1"}},
        {"type": "tool_result", "data": {"tool": "dnsx", "stage": "s1", "result": {}}},
        {"type": "stage_finished", "data": {"stage": "s1"}},
    ]
    units = group_units(events, autonomous=False)
    assert len(units) == 1
    assert units[0]["label"] == "stage s1"


def test_group_units_autonomous_by_agent_message():
    events = [
        {"type": "agent_message", "data": {"content": "try dnsx"}},
        {"type": "tool_call", "data": {"tool": "dnsx"}},
        {"type": "tool_result", "data": {"tool": "dnsx", "result": {}}},
        {"type": "agent_message", "data": {"content": "done"}},
    ]
    units = group_units(events, autonomous=True)
    assert len(units) == 2


def test_self_check_unit_parses_json():
    class Fake:
        def chat(self, messages, tools):
            return {"content": '[{"kind":"difficulty","text":"no result"}]', "tool_calls": []}

    notes = self_check_unit(Fake(), {"label": "stage s1", "tool_calls": [], "tool_results": []})
    assert notes == [{"kind": "difficulty", "text": "no result"}]


def test_evolution_report_parses_json():
    class Fake:
        def chat(self, messages, tools):
            return {
                "content": '{"summary":"ok","steps":[],"suggestions":[{"type":"add_tool","where":"s1","detail":"x"}],"unresolved":[],"confidence":"low"}',
                "tool_calls": [],
            }

    r = evolution_report(Fake(), {"name": "demo"}, [], [])
    assert r["suggestions"][0]["type"] == "add_tool"
    assert r["confidence"] == "low"
