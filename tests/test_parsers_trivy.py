"""Parser tests for trivy (dependency scan, json L1) (M2-A T0): sample / empty / broken inputs."""
from lattice_ai import toolchain_registry as tcr
from parsers_helpers import assert_facts_shape, load_sample, parse_sample, tcr_entry_parse


def test_sample_output_parses_to_facts():
    facts = parse_sample("trivy")
    assert_facts_shape(facts)
    assert facts["stats"]["total"] == 2
    first = facts["items"][0]
    assert first["type"] == "finding"
    assert first["value"] == "CVE-2021-23337"
    assert first["severity"] == "high"
    assert first["cve"] == ["CVE-2021-23337"]
    assert first["pkg"] == "lodash"
    assert first["fixed_version"] == "4.17.21"
    assert facts["items"][1]["severity"] == "critical"
    assert facts["items"][1]["cve"] == []  # GHSA id is not a CVE
    assert "critical" in facts["summary"]
    # a result target with no vulnerabilities contributes no items
    assert all(item["target"] != "requirements.txt" for item in facts["items"])


def test_empty_output_is_empty_facts():
    facts = tcr_entry_parse(tcr.get_entry("trivy"), "")
    assert_facts_shape(facts)
    assert facts["items"] == []
    assert facts["summary"] == "" or facts["stats"]["total"] == 0


def test_broken_json_degrades_without_raising():
    facts = tcr_entry_parse(tcr.get_entry("trivy"), "not json at all")
    assert_facts_shape(facts)
    assert facts["summary"].startswith("parse failed")
    assert facts["parse_error"]


def test_jsonl_masquerading_as_json_is_tolerated():
    line = '{"Results": [{"Target": "go.mod", "Type": "golang", "Vulnerabilities": [{"VulnerabilityID": "CVE-2025-22870", "PkgName": "golang.org/x/net", "Severity": "HIGH"}]}]}'
    facts = tcr_entry_parse(tcr.get_entry("trivy"), "warn noise" + chr(10) + line + chr(10) + "{broken")
    assert_facts_shape(facts)
    assert facts["stats"]["total"] == 1
    assert facts["items"][0]["value"] == "CVE-2025-22870"
