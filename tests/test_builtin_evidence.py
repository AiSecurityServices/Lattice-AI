from lattice_ai.builtins import install_builtins, record_finding, record_host, record_loot
from lattice_ai.tools import ToolRegistry


def test_record_finding_returns_recorded_payload():
    result = record_finding({"title": "Exposed admin", "severity": "high", "target": "example.com"})
    assert result["recorded"] is True
    assert result["finding"]["title"] == "Exposed admin"
    assert result["finding"]["severity"] == "high"
    assert result["finding"]["target"] == "example.com"


def test_record_finding_requires_title():
    result = record_finding({})
    assert result["recorded"] is False
    assert "error" in result


def test_record_loot_returns_recorded_payload():
    result = record_loot({"data": {"url": "https://example.com/backup.zip", "size": 1024}})
    assert result["recorded"] is True
    assert result["loot"]["url"] == "https://example.com/backup.zip"


def test_record_host_returns_recorded_payload():
    result = record_host({"host": "203.0.113.10", "kind": "ip"})
    assert result["recorded"] is True
    assert result["asset"]["value"] == "203.0.113.10"
    assert result["asset"]["kind"] == "ip"


def test_evidence_tools_registered_with_category():
    reg = ToolRegistry()
    install_builtins(reg)
    for name in ("record_finding", "record_loot", "record_host"):
        assert reg.get(name).category == "evidence"
