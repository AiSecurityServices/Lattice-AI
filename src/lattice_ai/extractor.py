import re

from lattice_ai.analyzer import ProjectModel
from lattice_ai.models import Skill, Tool


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (name or "").lower()).strip("-") or "tool"


def _default_params(parameters):
    return parameters or {"type": "object", "properties": {}}


def _as_cli(candidate, detail) -> Tool:
    return Tool(
        name=_slug(candidate.get("name", "tool")),
        description=detail or candidate.get("name", ""),
        runner="cli",
        command=[str(c) for c in (candidate.get("command") or [])],
        parameters=_default_params(candidate.get("parameters")),
    )


def _as_http(candidate, detail) -> Tool:
    cmd = candidate.get("command") or ["GET", ""]
    return Tool(
        name=_slug(candidate.get("name", "http")),
        description=detail or candidate.get("name", ""),
        runner="adapter",
        adapter="http_api",
        ref=candidate.get("ref", ""),
        command=[str(c) for c in cmd],
        parameters=_default_params(candidate.get("parameters")),
    )


def _as_mcp(candidate, detail) -> Tool:
    return Tool(
        name=_slug(candidate.get("name", "mcp")),
        description=detail or candidate.get("name", ""),
        runner="adapter",
        adapter="mcp",
        ref=candidate.get("ref", ""),
        command=[str(c) for c in (candidate.get("command") or [])],
        parameters=_default_params(candidate.get("parameters")),
    )


def extract_assets(model: ProjectModel):
    tools: list[Tool] = []
    skills: list[Skill] = []
    imports: list[dict] = []

    for cand in model.tools:
        name = _slug(cand.get("name", "tool"))
        ctype = (cand.get("type") or "cli").lower()
        detail = cand.get("detail", "")
        if ctype == "mcp":
            tools.append(_as_mcp(cand, detail))
            imports.append({"name": name, "kind": "mcp", "status": "imported", "detail": detail})
        elif ctype == "http_api":
            tools.append(_as_http(cand, detail))
            imports.append({"name": name, "kind": "http_api", "status": "imported", "detail": detail})
        elif ctype == "cli":
            tools.append(_as_cli(cand, detail))
            imports.append({"name": name, "kind": "cli", "status": "imported", "detail": detail})
        else:  # skill / sdk-internal
            skills.append(Skill(
                name=name,
                description=detail or cand.get("name", ""),
                content=cand.get("content") or cand.get("detail", ""),
                category="generated",
                tags=[],
            ))
            imports.append({
                "name": name,
                "kind": "skill",
                "status": "inferred",
                "detail": detail or "SDK 内部功能，已作为 Skill 绑定，需接入可执行入口",
            })

    for sk in model.skills:
        sname = _slug(sk.get("name", "skill"))
        if any(s.name == sname for s in skills):
            continue
        skills.append(Skill(
            name=sname,
            description=sk.get("description", ""),
            content=sk.get("content", ""),
            category=sk.get("category", "generated"),
            tags=[],
        ))
        imports.append({"name": sname, "kind": "skill", "status": "imported", "detail": sk.get("description", "")})

    return tools, skills, imports
