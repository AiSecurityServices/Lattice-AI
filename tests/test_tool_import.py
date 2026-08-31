import sys

from lattice_ai.models import Tool
from lattice_ai.tool_import import (
    classify_source,
    detect_mcp,
    import_tool_source,
    list_mcp_tools,
    map_target_to_args,
    mcp_tools_to_lattice,
    parse_command,
    script_tool_from_source,
)
from lattice_ai.tool_import import mcp_tool_to_lattice


def test_detect_mcp_by_known_command_prefixes():
    assert detect_mcp("npx -y @modelcontextprotocol/server-filesystem") is True
    assert detect_mcp("uvx security-mcp") is True
    assert detect_mcp("mcp://npx thing") is True


def test_detect_mcp_returns_false_for_plain_description():
    assert detect_mcp("run a port scan") is False


def test_parse_command_handles_quoted_path():
    parts = parse_command('"C:\\Program Files\\Python\\python.exe" -m lattice_ai.sample_mcp')
    assert parts[0] == "C:\\Program Files\\Python\\python.exe"
    assert parts[-1] == "lattice_ai.sample_mcp"


def test_list_mcp_tools_discovers_sample_tools():
    cmd = [sys.executable, "-m", "lattice_ai.sample_mcp"]
    tools = list_mcp_tools(cmd)
    names = {t["name"] for t in tools}
    assert "scan_port" in names


def test_mcp_tools_to_lattice_returns_tools_with_ask_default():
    tools = mcp_tools_to_lattice(
        [{"name": "scan_port", "description": "scan", "inputSchema": {"type": "object"}}],
        command=["python", "-m", "lattice_ai.sample_mcp"],
    )
    assert len(tools) == 1
    assert tools[0].approval == "ask"
    assert tools[0].adapter == "mcp"
    assert tools[0].ref == "scan_port"


def test_mcp_tool_to_lattice_rejects_empty_name():
    try:
        mcp_tool_to_lattice({"description": "no name"}, command=["x"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_mcp_tool_to_lattice_falls_back_for_non_dict_schema():
    tool = mcp_tool_to_lattice({"name": "x", "inputSchema": "not-a-dict"}, command=["x"])
    assert tool.parameters == {"type": "object", "properties": {}}


class FakeProvider:
    def chat(self, messages, tools):
        return {"content": '{"target": "example.com", "port": 80}'}


def test_map_target_to_args_parses_provider_json():
    tool = Tool(
        name="scan_port",
        runner="adapter",
        adapter="mcp",
        parameters={
            "type": "object",
            "properties": {"target": {"type": "string"}, "port": {"type": "integer"}},
        },
    )
    args = map_target_to_args(FakeProvider(), tool, "example.com")
    assert args == {"target": "example.com", "port": 80}


def test_classify_source_families():
    assert classify_source("npx -y security-mcp") == "mcp"
    assert classify_source("mcp://npx thing") == "mcp"
    assert classify_source("https://github.com/owner/repo") == "github"
    assert classify_source("https://example.com/tool") == "url"
    assert classify_source("tmp/tool.py") == "script"
    assert classify_source("run a scan") == "description"


def test_script_tool_from_source_uses_python_for_py_file(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text("print('x')")
    tool = script_tool_from_source(str(script))
    assert tool.runner == "cli"
    assert tool.command[0] == sys.executable
    assert tool.command[1] == str(script)
    assert tool.approval == "ask"


class DraftProvider:
    def chat(self, messages, tools):
        return {
            "content": (
                '{"name":"probe","description":"probe","runner":"cli",'
                '"command":["echo","{target}"],'
                '"parameters":{"type":"object","properties":{"target":{"type":"string"}}}}'
            )
        }


def test_import_tool_source_routes_description_to_tool():
    tools = import_tool_source(DraftProvider(), "scan ports")
    assert len(tools) == 1
    assert tools[0].name == "probe"
    assert tools[0].runner == "cli"
