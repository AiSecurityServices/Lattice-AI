"""Parser tests for naabu (port scan, jsonl L1) (T-U2): sample / empty / broken inputs."""
from lattice_ai import toolchain_registry as tcr
from parsers_helpers import assert_facts_shape, load_sample, parse_sample, tcr_entry_parse, values


def test_sample_output_parses_to_facts():
    facts = parse_sample("naabu")
    assert_facts_shape(facts)
    assert facts["stats"]["total"] == 3
    assert values(facts) == ["10.0.0.7:80", "10.0.0.7:443", "10.0.0.8:8080"]
    assert facts["items"][2]["port"] == 8080


def test_empty_output_is_empty_facts():
    facts = tcr_entry_parse(tcr.get_entry("naabu"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
    assert facts["summary"] == "" or facts["stats"]["total"] == 0


def test_broken_jsonl():
    stdout = "garbage line" + chr(10) + load_sample("naabu") + chr(10) + "{broken"
    facts = tcr_entry_parse(tcr.get_entry("naabu"), stdout)
    assert_facts_shape(facts)
    assert facts["stats"]["total"] >= 3  # garbage lines skipped, real rows kept

