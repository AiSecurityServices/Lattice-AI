import json
from dataclasses import dataclass, field
from pathlib import Path

from lattice_ai.resolver import ProjectSnapshot


@dataclass
class ProjectModel:
    summary: str = ""
    entrypoints: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    confidence: str = "low"
    gaps: list[str] = field(default_factory=list)


def _extract(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else "{}"


def _read(snapshot: ProjectSnapshot, path: str, read_file, cap: int = 20000) -> str:
    if read_file is not None:
        return read_file(path)
    root = Path(snapshot.root)
    try:
        if root.is_dir():
            return (root / path).read_text(encoding="utf-8", errors="replace")[:cap]
        return Path(path).read_text(encoding="utf-8", errors="replace")[:cap]
    except Exception:
        return ""


def _coerce(data: dict) -> ProjectModel:
    return ProjectModel(
        summary=str(data.get("summary", "")),
        entrypoints=list(data.get("entrypoints", [])),
        tools=list(data.get("tools", [])),
        skills=list(data.get("skills", [])),
        capabilities=list(data.get("capabilities", [])),
        dependencies=list(data.get("dependencies", [])),
        confidence=str(data.get("confidence", "low")),
        gaps=list(data.get("gaps", [])),
    )


def analyze_project(provider, snapshot: ProjectSnapshot, *, read_file=None, budget: int = 12) -> ProjectModel:
    if not snapshot.files:
        return ProjectModel(summary="（无来源，仅描述）", confidence="low", gaps=["无来源文件，仅依描述"])
    tree = "\n".join(f"{f.path} [{f.kind}] ({f.size}B)" for f in snapshot.files)
    plan_prompt = (
        "You are analyzing a security tool project. The file tree is below.\n"
        "List the files whose content is needed to understand its tools (CLI/API/MCP), skills, entrypoints, and workflow.\n"
        "Respond ONLY a JSON object: {\"files_to_read\": [\"relative/path\", ...]} (max 12).\n\nTree:\n" + tree
    )
    plan_resp = provider.chat([{"role": "user", "content": plan_prompt}], [])
    to_read = []
    try:
        data = json.loads(_extract(plan_resp.get("content")))
        to_read = data.get("files_to_read", [])[:budget]
    except Exception:
        to_read = [f.path for f in snapshot.files[:budget]]

    chunks = []
    for rel in to_read:
        content = _read(snapshot, rel, read_file)
        if content:
            chunks.append(f"=== {rel} ===\n{content[:20000]}")
    context = "\n\n".join(chunks) if chunks else tree

    synth_prompt = (
        "Analyze this project source and output a ProjectModel as ONE JSON object with keys:\n"
        "summary(string), entrypoints(list<string>), tools(list of {name,type(cli|mcp|http_api|skill),command(list<string>, optional),parameters(object, optional),ref(string, optional),detail(string)}), "
        "skills(list of {name, description, content, category}), capabilities(list<string>), dependencies(list<string>), "
        "confidence(high|medium|low), gaps(list<string>).\n"
        "Do not invent commands. If a capability is SDK-internal with no external interface, mark type=skill and note in gaps.\n\n"
        "Project source:\n" + context[:60000]
    )
    resp = provider.chat([{"role": "user", "content": synth_prompt}], [])
    raw = _extract(resp.get("content"))
    try:
        data = json.loads(raw)
    except Exception:
        data = {"summary": raw[:500], "confidence": "low", "gaps": ["LLM 未返回有效 JSON，已降级"]}
    return _coerce(data)
