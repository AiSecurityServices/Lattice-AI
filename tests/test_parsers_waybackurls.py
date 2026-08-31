"""Parser tests for waybackurls (archive URLs, text L2) (T-U2): sample / empty / broken inputs."""
from lattice_ai import toolchain_registry as tcr
from parsers_helpers import assert_facts_shape, load_sample, parse_sample, tcr_entry_parse, values


def test_sample_output_parses_to_facts():
    facts = parse_sample("waybackurls")
    assert_facts_shape(facts)
    assert facts["stats"]["total"] == 2
    assert values(facts)[1] == "http://example.com/backup.zip"


def test_empty_output_is_empty_facts():
    facts = tcr_entry_parse(tcr.get_entry("waybackurls"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
    assert facts["summary"] == "" or facts["stats"]["total"] == 0


def test_broken_lines():
    facts = tcr_entry_parse(tcr.get_entry("waybackurls"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
