"""Parser tests for ffuf (content fuzzing, json L1) (T-U2): sample / empty / broken inputs."""
from lattice_ai import toolchain_registry as tcr
from parsers_helpers import assert_facts_shape, load_sample, parse_sample, tcr_entry_parse, values


def test_sample_output_parses_to_facts():
    facts = parse_sample("ffuf")
    assert_facts_shape(facts)
    assert facts["stats"]["total"] == 2
    first = facts["items"][0]
    assert first["value"] == "https://example.com/admin"
    assert first["status"] == 200 and first["input"] == "admin"


def test_empty_output_is_empty_facts():
    facts = tcr_entry_parse(tcr.get_entry("ffuf"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
    assert facts["summary"] == "" or facts["stats"]["total"] == 0


def test_broken_json():
    facts = tcr_entry_parse(tcr.get_entry("ffuf"), "{not json")
    assert facts["summary"].startswith("parse failed")
    assert facts["parse_error"]

