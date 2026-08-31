"""M3-B T3: nuclei-templates → Skill import, idempotent, fixture-based (no
real clone needed)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from lattice_ai.library import SkillStore

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "import_nuclei_templates.py"
_spec = importlib.util.spec_from_file_location("import_nuclei_templates", _SCRIPT)
imp = importlib.util.module_from_spec(_spec)
sys.modules["import_nuclei_templates"] = imp
_spec.loader.exec_module(imp)

_TEMPLATE_YAML = """id: {tid}
info:
  name: {name}
  author: owner
  severity: {severity}
  description: {desc}
  remediation: upgrade the component
  reference:
    - https://example.com/advisory/{tid}
  metadata:
    verified: true
  classification:
    cvss-score: 9.8
    cve-id: {cve}
    cwe-id: CWE-79
    epss-score: 0.001
  tags: [cve, rce, http]
"""


def _write_template(root: Path, category: str, tid: str, *, name="Broken Auth", severity="critical",
                    desc="An authenticated bypass.", cve="CVE-2024-1234"):
    directory = root / category
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{tid}.yaml").write_text(
        _TEMPLATE_YAML.format(tid=tid, name=name, severity=severity, desc=desc, cve=cve),
        encoding="utf-8",
    )


@pytest.fixture
def clone(tmp_path):
    root = tmp_path / "nuclei-templates"
    root.mkdir()
    _write_template(root, "http/exposures", "exposed-panel")
    _write_template(root, "http/vulnerabilities", "rce-critical")
    _write_template(root, "http/misconfiguration", "open-dash", severity="high")
    # filtered out: medium severity
    _write_template(root, "http/vulnerabilities", "low-sev", severity="medium")
    # filtered out: not verified
    (root / "http/exposures/unverified.yaml").write_text(
        _TEMPLATE_YAML.format(tid="unverified", name="No Verify", severity="critical",
                              desc="d", cve="CVE-2024-1").replace("verified: true", "verified: false"),
        encoding="utf-8",
    )
    return root


def test_import_creates_curated_skills_and_is_idempotent(clone, tmp_path):
    store = SkillStore(tmp_path / "skills")
    counts = imp.import_nuclei_templates(clone, store)
    assert counts == {"created": 3, "updated": 0, "skipped": 0}

    skills = {s["name"]: s for s in store.list()}
    assert set(skills) == {"exposed-panel", "rce-critical", "open-dash"}
    skill = skills["rce-critical"]
    assert skill["source"] == "nuclei"
    assert skill["category"] == "nuclei-detect"
    assert skill["classification"]["cve"] == "CVE-2024-1234"
    assert skill["classification"]["cwe"] == "CWE-79"
    assert skill["classification"]["cvss"] == "9.8"
    assert skill["classification"]["severity"] == "critical"
    assert skill["tags"] == ["cve", "rce", "http"]
    # content is assembled only from the template's own fields + provenance
    assert "An authenticated bypass." in skill["content"]
    assert "upgrade the component" in skill["content"]
    assert "https://example.com/advisory/rce-critical" in skill["content"]
    assert "Template id: rce-critical" in skill["content"]

    # rerun: identical content → all skipped, nothing duplicated
    assert imp.import_nuclei_templates(clone, store) == {"created": 0, "updated": 0, "skipped": 3}
    assert len(store.list()) == 3


def test_import_updates_when_template_content_changes(clone, tmp_path):
    store = SkillStore(tmp_path / "skills")
    imp.import_nuclei_templates(clone, store)
    _write_template(clone, "http/exposures", "exposed-panel", desc="UPDATED description text.")
    counts = imp.import_nuclei_templates(clone, store)
    assert counts == {"created": 0, "updated": 1, "skipped": 2}
    skill = {s["name"]: s for s in store.list()}["exposed-panel"]
    assert "UPDATED description text." in skill["content"]


def test_limit_and_duplicate_ids(clone, tmp_path):
    store = SkillStore(tmp_path / "skills")
    counts = imp.import_nuclei_templates(clone, store, limit=2)
    assert counts["created"] == 2

    # a second file with the same template id is skipped
    _write_template(clone, "http/exposures", "exposed-panel")  # same id again (same content path differs)
    counts = imp.import_nuclei_templates(clone, store, limit=100)
    assert {s["name"] for s in store.list()} == {"exposed-panel", "rce-critical", "open-dash"}


def test_missing_clone_directory_is_a_noop(tmp_path):
    store = SkillStore(tmp_path / "skills")
    counts = imp.import_nuclei_templates(tmp_path / "nonexistent", store)
    assert counts == {"created": 0, "updated": 0, "skipped": 0}


def test_tags_comma_separated_string_is_split_not_iterated(clone, tmp_path):
    """Real nuclei templates write `tags: cve,rce,http` (a plain string);
    iterating it would yield single characters."""
    (clone / "http/exposures/comma-tags.yaml").write_text(
        _TEMPLATE_YAML.format(tid="comma-tags", name="T", severity="high", desc="d", cve="CVE-2024-9")
          .replace("tags: [cve, rce, http]", "tags: cve,rce,http"),
        encoding="utf-8",
    )
    store = SkillStore(tmp_path / "skills")
    imp.import_nuclei_templates(clone, store)
    skill = {s["name"]: s for s in store.list()}["comma-tags"]
    assert skill["tags"] == ["cve", "rce", "http"]


def test_default_skills_root_matches_runtime_store():
    """Rework ② guard: the script's default destination must be exactly the
    server's skill library root, not a sibling data dir."""
    from pathlib import Path

    from lattice_ai import runtime

    assert imp.default_skills_root().resolve() == Path(runtime._skill_store.root).resolve()
