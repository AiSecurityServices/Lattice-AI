from lattice_ai.models import GateRule, RunState, Stage, Template, Tool, from_dict, to_dict


def test_stage_has_dag_fields():
    s = Stage(id="recon", name="Recon", depends_on=[], condition=None, gates=[
        GateRule(name="has_endpoints", check={"op": "truthy", "key": "subfinder.subdomains"},
                 on_fail="block")
    ])
    d = to_dict(s)
    assert d["gates"][0]["on_fail"] == "block"
    assert from_dict(Stage, d).gates[0].name == "has_endpoints"


def test_template_has_version_and_no_transitions():
    t = Template(id="t", name="T", start="a", stages=[Stage(id="a", name="A")])
    d = to_dict(t)
    assert d["version"] == 1
    assert "transitions" not in d


def test_tool_category_enabled_and_runstate_roundtrip():
    tool = Tool(name="subfinder", runner="builtin", category="recon", enabled=True)
    assert tool.category == "recon"
    rs = RunState(run_id="r1", template_id="t", target="x", stage_status={"a": "completed"})
    assert from_dict(RunState, to_dict(rs)).run_id == "r1"
