import sys

from lattice_ai.cli import main
from lattice_ai.models import Stage, Template, Tool, ToolBinding
from lattice_ai.persistence import save_template


def test_cli_run(tmp_path, capsys):
    tool = Tool(
        name="print",
        description="print",
        runner="cli",
        command=[sys.executable, "-c", "import sys; print(sys.argv[1])", "{target}"],
    )
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="print", key="out")])],
        tools=[tool],
    )
    template_path = tmp_path / "template.json"
    save_template(template, template_path)
    out_path = tmp_path / "session.jsonl"

    main([str(template_path), "example.com", "--out", str(out_path)])

    assert out_path.exists()
    assert "example.com" in capsys.readouterr().out


def test_cli_run_builtin_tool(tmp_path, capsys):
    tool = Tool(name="echo", description="echo", runner="builtin")
    template = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a", tools=[ToolBinding(tool="echo", key="out", defaults={"msg": "hi"})])],
        tools=[tool],
    )
    template_path = tmp_path / "template.json"
    save_template(template, template_path)
    out_path = tmp_path / "session.jsonl"

    main([str(template_path), "example.com", "--out", str(out_path)])

    assert out_path.exists()
    assert '"value": "hi"' in capsys.readouterr().out
