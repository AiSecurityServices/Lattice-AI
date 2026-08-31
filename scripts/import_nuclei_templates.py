"""Import a curated subset of projectdiscovery/nuclei-templates into the
Lattice Skill knowledge base.

nuclei-templates is MIT-licensed, so its content may be stored verbatim; this
script only ORGANIZES each template's own fields (description / remediation /
reference) into a Skill markdown body — no rewritten or external copy — and
keeps provenance via ``source="nuclei"`` plus the template id and reference
links inside the content.

Usage:
    git clone --depth 1 https://github.com/projectdiscovery/nuclei-templates
    python scripts/import_nuclei_templates.py /path/to/nuclei-templates

Curated default (overridable via --category / --limit): http/exposures,
http/misconfiguration and http/vulnerabilities templates whose
``info.severity`` is critical/high AND ``info.metadata.verified: true``,
capped at 800. Import is idempotent: same name + same content hash → skipped,
changed content → updated, so re-runs and interrupted runs never duplicate.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

# Make `lattice_ai` importable when the script runs from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lattice_ai.library import SkillStore  # noqa: E402

DEFAULT_CATEGORIES = ("http/exposures", "http/misconfiguration", "http/vulnerabilities")
DEFAULT_LIMIT = 800
SEVERITIES = {"critical", "high"}


def parse_template_file(path: Path) -> dict | None:
    """Load one nuclei template YAML; None when it is not a curated candidate
    (missing id/info, severity outside {critical, high}, or not verified)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    template_id = str(data.get("id") or "").strip()
    info = data.get("info")
    if not template_id or not isinstance(info, dict):
        return None
    if str(info.get("severity") or "").lower() not in SEVERITIES:
        return None
    metadata = info.get("metadata") if isinstance(info.get("metadata"), dict) else {}
    if not metadata.get("verified"):
        return None
    return data


def build_content(data: dict) -> str:
    """Markdown body assembled strictly from the template's own fields."""
    info = data.get("info") or {}
    lines = [f"# {info.get('name') or data.get('id')}"]
    if info.get("description"):
        lines += ["", str(info["description"]).strip()]
    if info.get("remediation"):
        lines += ["", "## Remediation", "", str(info["remediation"]).strip()]
    references = info.get("reference") or []
    if isinstance(references, str):
        references = [references]
    references = [str(r) for r in references if r]
    if references:
        lines += ["", "## References"] + [f"- {reference}" for reference in references]
    lines += ["", f"Template id: {data.get('id')} (projectdiscovery/nuclei-templates, MIT)"]
    return "\n".join(lines).strip()


def build_skill(data: dict) -> dict:
    info = data.get("info") or {}
    classification = info.get("classification") if isinstance(info.get("classification"), dict) else {}
    # nuclei templates usually write tags as a comma-separated string, not a
    # YAML list — iterating the string would yield single characters.
    raw_tags = info.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")
    tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()][:8]
    return {
        "name": str(data.get("id")),
        "description": str(info.get("name") or ""),
        "category": "nuclei-detect",
        "tags": tags,
        "content": build_content(data),
        "source": "nuclei",
        "classification": {
            "cve": str(classification.get("cve-id") or ""),
            "cwe": str(classification.get("cwe-id") or ""),
            "cvss": str(classification.get("cvss-score") or ""),
            "epss": str(classification.get("epss-score") or ""),
            "severity": str(info.get("severity") or "").lower(),
        },
    }


def collect_templates(root: Path, categories, limit: int) -> list[dict]:
    skills: list[dict] = []
    seen_ids: set[str] = set()
    for category in categories:
        if len(skills) >= limit:
            break
        directory = root / category
        if not directory.is_dir():
            continue
        for path in sorted(list(directory.rglob("*.yaml")) + list(directory.rglob("*.yml"))):
            if len(skills) >= limit:
                break
            data = parse_template_file(path)
            if data is None:
                continue
            template_id = str(data.get("id"))
            if template_id in seen_ids:
                continue  # duplicate id inside the curated set → skip
            seen_ids.add(template_id)
            skills.append(build_skill(data))
    return skills


def import_nuclei_templates(root, store: SkillStore, categories=None, limit: int = DEFAULT_LIMIT) -> dict:
    root = Path(root)
    categories = tuple(categories) if categories else DEFAULT_CATEGORIES
    skills = collect_templates(root, categories, limit)
    return store.upsert_many(skills)


def default_skills_root() -> Path:
    """The server's global Skill library — same root as runtime._skill_store
    (runtime resolves data/ from <repo>/src/lattice_ai three levels up, which
    for the package __init__ is parents[2])."""
    import lattice_ai

    return Path(lattice_ai.__file__).resolve().parents[2] / "data" / "skills"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clone_dir", help="path to a local nuclei-templates clone")
    parser.add_argument(
        "--skills-dir",
        default=None,
        help="SkillStore root (default: the server's data/skills directory)",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="max templates to import")
    parser.add_argument(
        "--category",
        action="append",
        default=None,
        help="template category dir to include (repeatable; default: the curated three)",
    )
    args = parser.parse_args(argv)

    skills_dir = Path(args.skills_dir) if args.skills_dir else default_skills_root()
    store = SkillStore(skills_dir)
    counts = import_nuclei_templates(args.clone_dir, store, categories=args.category, limit=args.limit)
    print(
        f"nuclei-templates import complete: created={counts['created']} "
        f"updated={counts['updated']} skipped={counts['skipped']} → {skills_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
