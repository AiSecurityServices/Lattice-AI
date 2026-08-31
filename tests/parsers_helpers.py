"""Shared helpers for the per-tool parser tests (T-U2)."""
from pathlib import Path

from lattice_ai import toolchain_registry as tcr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parsers"


def load_sample(name: str) -> str:
    files = sorted((FIXTURES / name).glob("sample.*"))
    assert files, f"no sample fixture for {name}"
    return files[0].read_text(encoding="utf-8")


def parse_sample(name: str) -> dict:
    entry = tcr.get_entry(name)
    assert entry is not None, f"{name} missing from toolchain registry"
    return tcr_entry_parse(entry, load_sample(name))


def tcr_entry_parse(entry, stdout: str) -> dict:
    from lattice_ai.parsers import parse_for_entry

    return parse_for_entry(entry, stdout, "", 0)


def assert_facts_shape(facts: dict) -> None:
    """The T-U3 facts contract every parser must honour."""
    assert set(facts) >= {"summary", "items", "stats", "raw"}
    assert isinstance(facts["summary"], str) and len(facts["summary"]) <= 300
    assert isinstance(facts["items"], list)
    assert isinstance(facts["stats"], dict) and isinstance(facts["stats"]["total"], int)
    assert facts["stats"]["total"] == len(facts["items"])
    assert isinstance(facts["raw"], str)
    for item in facts["items"]:
        assert "type" in item and "value" in item
        assert item["type"] in ("domain", "url", "host", "port", "finding")


def values(facts: dict) -> list[str]:
    return [item["value"] for item in facts["items"]]
