import hashlib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportPreview:
    source: str
    fingerprint: str
    assets: list[dict] = field(default_factory=list)
    suggested_bindings: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fetch_text(url: str, timeout: float = 10.0) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lattice-ai"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")[:20000]
    except Exception:
        return None


def _raw_skill_urls(source: str) -> list[str]:
    value = (source or "").strip()
    urls = []
    if value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        if parsed.netloc == "raw.githubusercontent.com":
            urls.append(value)
        elif "github.com" in parsed.netloc:
            m = re.search(r"github\.com/([^/]+)/([^/]+)(/blob/([^/]+)/(.+))?", value)
            if m:
                owner, repo = m.group(1), m.group(2)
                branch = m.group(4)
                path = m.group(5)
                if path:
                    urls.append(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}")
                else:
                    for b in ("main", "master"):
                        urls.append(f"https://raw.githubusercontent.com/{owner}/{repo}/{b}/SKILL.md")
                        urls.append(f"https://raw.githubusercontent.com/{owner}/{repo}/{b}/README.md")
    return urls


def _skill_asset(content: str) -> dict:
    name_match = re.search(r"^#\s+(.+)$", content, re.M)
    return {
        "type": "skill",
        "name": (name_match.group(1) if name_match else "imported-skill").strip().lower().replace(" ", "-"),
        "description": content.strip().splitlines()[0][:200] if content.strip() else "",
        "content": content,
        "warnings": [],
    }


def preview_asset_import(provider, source: str) -> ImportPreview:
    value = (source or "").strip()
    fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    preview = ImportPreview(source=value, fingerprint=fingerprint)

    local = Path(value)
    if local.exists():
        content = local.read_text(encoding="utf-8", errors="replace")[:20000]
        if local.name.lower() == "skill.md":
            preview.assets.append(_skill_asset(content))
        else:
            preview.warnings.append("local file is not SKILL.md; only SKILL.md is supported")
        return preview

    for url in _raw_skill_urls(value):
        content = _fetch_text(url)
        if not content:
            continue
        if url.lower().endswith("skill.md"):
            preview.assets.append(_skill_asset(content))
        elif url.lower().endswith("readme.md"):
            preview.warnings.append("README.md detected; full tool generation requires LLM preview step")
    if not preview.assets:
        preview.warnings.append("no SKILL.md asset could be read from the source")
    return preview
