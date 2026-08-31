"""Parser tests for subfinder (subdomain enum, jsonl L1) (T-U2): sample / empty / broken inputs."""
from lattice_ai import toolchain_registry as tcr
from parsers_helpers import assert_facts_shape, load_sample, parse_sample, tcr_entry_parse, values


def test_sample_output_parses_to_facts():
    facts = parse_sample("subfinder")
    assert_facts_shape(facts)
    assert facts["stats"]["total"] == 2
    assert values(facts) == ["api.example.com", "dev.example.com"]
    assert facts["items"][0]["source"] == "crt.sh"


def test_empty_output_is_empty_facts():
    facts = tcr_entry_parse(tcr.get_entry("subfinder"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
    assert facts["summary"] == "" or facts["stats"]["total"] == 0


def test_broken_jsonl():
    stdout = "garbage line" + chr(10) + load_sample("subfinder") + chr(10) + "{broken"
    facts = tcr_entry_parse(tcr.get_entry("subfinder"), stdout)
    assert_facts_shape(facts)
    assert facts["stats"]["total"] >= 2  # garbage lines skipped, real rows kept

