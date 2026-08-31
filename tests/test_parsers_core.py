"""Core tests for the T-U3 output parser layer and the reworked
_normalize_cli_output (parse on FULL stdout, truncate raw afterwards)."""
import json

from lattice_ai import parsers, toolchain_registry as tcr
from lattice_ai.events import EventLog
from lattice_ai.builtins import install_builtins
from lattice_ai.models import Tool
from lattice_ai.tools import ToolRegistry

from helpers_fakeexe import make_fake_exe, version_flag_of


def _entry(name: str) -> tcr.RegistryEntry:
    entry = tcr.get_entry(name)
    assert entry is not None
    return entry


def test_parse_returns_none_for_non_registry_tool():
    tool = Tool(name="my-own-tool", runner="cli", command=["whatever"])
    assert parsers.parse(tool, "{}", "", 0) is None


def test_l1_jsonl_happy_path_contract_shape():
    stdout = '\n'.join([
        json.dumps({"host": "a.example.com", "source": "crt.sh"}),
        json.dumps({"host": "b.example.com", "source": "hackertarget"}),
    ])
    facts = parsers.parse_for_entry(_entry("subfinder"), stdout, "", 0)
    assert facts["summary"] == "2 个子域"
    assert facts["stats"]["total"] == 2
    assert facts["items"][0] == {"type": "domain", "value": "a.example.com", "source": "crt.sh"}
    assert facts["raw"] == stdout
    assert "parse_error" not in facts


def test_empty_output_yields_empty_facts_not_error():
    facts = parsers.parse_for_entry(_entry("subfinder"), "", "", 0)
    assert facts["items"] == []
    assert facts["stats"]["total"] == 0
    assert "parse_error" not in facts


def test_jsonl_tolerates_garbage_lines():
    stdout = "not json at all\n" + json.dumps({"host": "ok.example.com"}) + "\n{broken\n"
    facts = parsers.parse_for_entry(_entry("subfinder"), stdout, "", 0)
    assert [i["value"] for i in facts["items"]] == ["ok.example.com"]


def test_json_format_invalid_stdout_degrades_without_raising():
    facts = parsers.parse_for_entry(_entry("ffuf"), "this is not json", "", 0)
    assert facts["summary"].startswith("parse failed")
    assert facts["parse_error"]
    assert facts["raw"] == "this is not json"
    assert facts["items"] == []


def test_parse_uses_full_stdout_before_truncation():
    # rows beyond the 20k truncation marker must still be parsed
    rows = [{"host": f"h{i}.example.com"} for i in range(800)]
    stdout = "\n".join(json.dumps(r) for r in rows)
    assert len(stdout) > 20000
    facts = parsers.parse_for_entry(_entry("subfinder"), stdout, "", 0)
    assert facts["stats"]["total"] == 800
    assert len(facts["raw"]) <= 20000 + len("...[truncated]")


def test_summary_is_capped_at_300_chars():
    stdout = "\n".join(json.dumps({"host": f"{i}.example.com"}) for i in range(200))
    facts = parsers.parse_for_entry(_entry("subfinder"), stdout, "", 0)
    assert len(facts["summary"]) <= 300


def test_nmap_xml_parse():
    stdout = (
        "<nmaprun><host>"
        "<address addr='10.0.0.7' addrtype='ipv4'/>"
        "<ports>"
        "<port protocol='tcp' portid='80'><state state='open'/></port>"
        "<port protocol='tcp' portid='443'><state state='open'/></port>"
        "<port protocol='tcp' portid='22'><state state='closed'/></port>"
        "</ports></host></nmaprun>"
    )
    facts = parsers.parse_for_entry(_entry("nmap"), stdout, "", 0)
    assert facts["summary"].startswith("1 台主机")
    hosts = [i for i in facts["items"] if i["type"] == "host"]
    ports = [i for i in facts["items"] if i["type"] == "port"]
    assert hosts and hosts[0]["value"] == "10.0.0.7"
    assert {p["port"] for p in ports} == {80, 443}


def test_nmap_broken_xml_degrades():
    facts = parsers.parse_for_entry(_entry("nmap"), "<nmaprun><host>", "", 0)
    assert facts["parse_error"]


def test_l2_line_parser_gau():
    stdout = "https://a.example.com/x\n\nhttps://b.example.com/y?z=1\nnot-a-url\n"
    facts = parsers.parse_for_entry(_entry("gau"), stdout, "", 0)
    assert facts["stats"]["total"] == 2
    assert all(i["type"] == "url" for i in facts["items"])
    assert facts["items"][1]["value"] == "https://b.example.com/y?z=1"


def test_registry_run_emits_parse_fallback_event(tmp_path):
    """A real-looking ffuf whose payload is not JSON degrades and logs the event."""
    entry = _entry("ffuf")
    flag = version_flag_of(entry.version_cmd)
    make_fake_exe(tmp_path, "ffuf", version_flag=flag,
                  version_line="ffuf version: 2.1.0", payload="broken-output")
    from lattice_ai.tools import add_tool_path
    add_tool_path(str(tmp_path))

    log = EventLog(tmp_path / "events.jsonl")
    registry = ToolRegistry()
    install_builtins(registry)
    result = registry.run("ffuf", {"target": "http://example.com"}, event_log=log)

    assert result["parse_error"]
    events = [e for e in log.read() if e.type == "parse_fallback"]
    assert len(events) == 1
    assert events[0].data["tool"] == "ffuf"
    assert events[0].data["reason"]


def test_registry_run_skips_event_when_parse_ok(tmp_path):
    entry = _entry("subfinder")
    flag = version_flag_of(entry.version_cmd)
    payload = json.dumps({"host": "x.example.com"})
    make_fake_exe(tmp_path, "subfinder", version_flag=flag,
                  version_line="v2.6.7", payload=payload)
    from lattice_ai.tools import add_tool_path
    add_tool_path(str(tmp_path))

    log = EventLog(tmp_path / "events.jsonl")
    registry = ToolRegistry()
    install_builtins(registry)
    result = registry.run("subfinder", {"target": "example.com"}, event_log=log)

    assert result["items"][0]["value"] == "x.example.com"
    assert not [e for e in log.read() if e.type == "parse_fallback"]
