"""Parser tests for dalfox (XSS scan, json L1) (T-U2): sample / empty / broken inputs."""
from lattice_ai import toolchain_registry as tcr
from parsers_helpers import assert_facts_shape, load_sample, parse_sample, tcr_entry_parse, values


def test_sample_output_parses_to_facts():
    facts = parse_sample("dalfox")
    assert_facts_shape(facts)
    assert facts["stats"]["total"] == 2
    first = facts["items"][0]
    assert first["severity"] == "high"
    assert "svg" in first["value"]
    assert facts["items"][1]["msg"].startswith("Grep")


def test_empty_output_is_empty_facts():
    facts = tcr_entry_parse(tcr.get_entry("dalfox"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
    assert facts["summary"] == "" or facts["stats"]["total"] == 0


def test_broken_json():
    facts = tcr_entry_parse(tcr.get_entry("dalfox"), "{not json")
    assert facts["summary"].startswith("parse failed")
    assert facts["parse_error"]

