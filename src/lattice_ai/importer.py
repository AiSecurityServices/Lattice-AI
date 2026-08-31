import json
import re
import urllib.parse
import urllib.request


_PROMPT = """You are importing a security tool. Given the description, output a single JSON object with exactly these fields:
- "name": short snake_case identifier
- "description": one sentence
- "runner": "cli"
- "command": list of argv strings, using {placeholder} for runtime arguments
- "parameters": a JSON Schema object, e.g. {"type": "object", "properties": {...}}

Description:
{description}

{context}

Return ONLY the JSON object, with no surrounding text."""

_URL_RE = re.compile(r"https?://[^\s]+")
_GITHUB_BLOB_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/blob/([^/\s]+)/([^\s]+)")
_GITHUB_REPO_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/?")


def _fetch_text(url: str, timeout: float = 10.0) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lattice-ai"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")[:20000]
    except Exception:
        return None


def _extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,);]") for u in _URL_RE.findall(text or "")]


def _github_context(text: str) -> str | None:
    for url in _extract_urls(text):
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        if host == "raw.githubusercontent.com":
            content = _fetch_text(url)
            if content:
                return content
            continue
        if host == "github.com":
            blob = _GITHUB_BLOB_RE.search(url)
            if blob:
                raw = f"https://raw.githubusercontent.com/{blob.group(1)}/{blob.group(2)}/{blob.group(3)}/{blob.group(4)}"
                content = _fetch_text(raw)
                if content:
                    return content
                continue
            repo = _GITHUB_REPO_RE.search(url)
            if repo:
                owner, repo_name = repo.group(1), repo.group(2)
                for branch in ("main", "master"):
                    content = _fetch_text(f"https://raw.githubusercontent.com/{owner}/{repo_name}/{branch}/README.md")
                    if content:
                        return content
            continue
    return None


def generate_tool_draft(provider, description: str) -> dict:
    context = _github_context(description)
    context_block = f"Relevant README/source content:\n{context}" if context else ""
    prompt = _PROMPT.replace("{description}", description).replace("{context}", context_block)
    messages = [{"role": "user", "content": prompt}]
    response = provider.chat(messages, [])
    content = response.get("content") or ""
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("provider did not return a JSON object")
    return json.loads(content[start : end + 1])


_OUTPUT_SCHEMA_PROMPT = """You are normalizing a security tool's output. Given the tool description and one
sample of its real output, produce a JSON Schema ({"type": "object", "properties": {...}})
describing the output object. Keep property names exactly as they appear in the sample.
Return ONLY the JSON Schema object.

Tool: {name}
Description: {description}

Sample output:
{sample}
"""


def generate_output_schema(provider, tool: dict, sample_output: str) -> dict:
    """Derive a Tool.output JSON Schema from one real output sample."""
    prompt = (
        _OUTPUT_SCHEMA_PROMPT
        .replace("{name}", str(tool.get("name") or ""))
        .replace("{description}", str(tool.get("description") or ""))
        .replace("{sample}", (sample_output or "")[:8000])
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    content = (response.get("content") or "").strip()
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("provider did not return a JSON schema")
    schema = json.loads(content[start : end + 1])
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("provider did not return an object schema")
    return schema

