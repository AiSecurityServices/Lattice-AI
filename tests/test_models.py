from lattice_ai.models import (
    Evidence,
    Finding,
    Stage,
    Template,
    Tool,
    ToolBinding,
    from_dict,
    to_dict,
)


def test_evidence_roundtrip():
    e = Evidence(id="evt_1", run_id="run_1", stage_id="ports", tool="nmap", args={"target": "x"}, result={"ports": [80]})
    assert from_dict(Evidence, to_dict(e)) == e


def test_finding_roundtrip():
    f = Finding(id="F-1", title="SQLi", severity="high", evidence_ids=["evt_1"])
    assert from_dict(Finding, to_dict(f)) == f


def make_template():
    tool = Tool(
        name="nmap",
        description="port scan",
        runner="cli",
        command=["nmap", "{target}"],
        parameters={"type": "object", "properties": {"target": {"type": "string"}}},
    )
    stage = Stage(id="recon", name="recon", tools=[ToolBinding(tool="nmap", key="nmap")])
    return Template(
        id="t1",
        name="demo",
        start="recon",
        stages=[stage],
        tools=[tool],
    )


def test_roundtrip_preserves_data():
    template = make_template()
    restored = from_dict(Template, to_dict(template))
    assert restored == template


def test_to_dict_shape():
    data = to_dict(make_template())
    assert data["start"] == "recon"
    assert data["stages"][0]["tools"][0]["tool"] == "nmap"


def test_roundtrip_with_nested_dicts():
    tool = Tool(
        name="t",
        description="d",
        runner="cli",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        output={"type": "object"},
    )
    binding = ToolBinding(
        tool="t",
        key="out",
        condition={"op": "truthy", "key": "a.b"},
        defaults={"x": "y"},
        args_from={"x": "a.b"},
    )
    template = Template(
        id="t",
        name="n",
        start="s",
        stages=[Stage(id="s", name="s", tools=[binding])],
        tools=[tool],
    )
    assert from_dict(Template, to_dict(template)) == template


def test_tool_policy_fields_roundtrip():
    tool = Tool(
        name="t",
        description="d",
        approval="ask",
        secret_fields=["password", "token.value"],
    )
    template = Template(
        id="t",
        name="n",
        start="s",
        stages=[Stage(id="s", name="s")],
        tools=[tool],
    )
    assert from_dict(Template, to_dict(template)) == template


def test_tool_adapter_fields_roundtrip():
    tool = Tool(
        name="mcp_tool",
        description="call a tool",
        runner="adapter",
        adapter="mcp",
        ref="search",
        command=["npx", "-y", "mcp-server"],
        parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        output={},
    )
    restored = from_dict(Tool, to_dict(tool))
    assert restored.runner == "adapter"
    assert restored.adapter == "mcp"
    assert restored.ref == "search"
    assert restored.command == ["npx", "-y", "mcp-server"]


def test_tool_adapter_defaults_empty():
    tool = from_dict(Tool, {"name": "x", "runner": "cli"})
    assert tool.adapter == ""
    assert tool.ref == ""


def test_finding_new_fields_have_defaults():
    finding = Finding(id="f1", title="test")
    assert finding.run_id == ""
    assert finding.affected_asset == ""
    assert finding.repro_steps == []
    assert finding.dedup_key == ""
