"""Parser tests for nmap (service scan, XML L3) (T-U2): sample / empty / broken inputs."""
from lattice_ai import toolchain_registry as tcr
from parsers_helpers import assert_facts_shape, load_sample, parse_sample, tcr_entry_parse, values


def test_sample_output_parses_to_facts():
    facts = parse_sample("nmap")
    assert_facts_shape(facts)
    hosts = [i for i in facts["items"] if i["type"] == "host"]
    ports = [i for i in facts["items"] if i["type"] == "port"]
    assert len(hosts) == 2
    assert {p["port"] for p in ports} == {80, 443, 8080}
    assert hosts[0]["value"] == "93.184.216.34"


def test_empty_output_is_empty_facts():
    facts = tcr_entry_parse(tcr.get_entry("nmap"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
    assert facts["parse_error"]  # empty XML is a parse failure; the run must not break


def test_broken_xml():
    facts = tcr_entry_parse(tcr.get_entry("nmap"), "<nmaprun><host>")
    assert facts["parse_error"]

