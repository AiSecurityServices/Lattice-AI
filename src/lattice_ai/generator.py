import json
import re

from lattice_ai.analyzer import ProjectModel
from lattice_ai.graph import validate_template
from lattice_ai.models import Skill, Template, Tool, from_dict, to_dict


def _extract(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else "{}"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (name or "").lower()).strip("-") or "template"


def generate_template(provider, model: ProjectModel, tools: list[Tool], skills: list[Skill], name: str = ""):
    tool_defs = [
        {
            "name": t.name, "description": t.description, "runner": t.runner,
            "command": t.command, "parameters": t.parameters, "adapter": t.adapter, "ref": t.ref,
        }
        for t in tools
    ]
    skill_defs = [
        {"name": s.name, "description": s.description, "category": s.category, "content": s.content}
        for s in skills
    ]
    prompt = (
        "Given this project model and its extracted tools/skills, produce a workflow Template JSON.\n"
        f"Project: {json.dumps(model.__dict__, ensure_ascii=False)}\n"
        f"Tools: {json.dumps(tool_defs, ensure_ascii=False)}\n"
        f"Skills: {json.dumps(skill_defs, ensure_ascii=False)}\n"
        "Output ONE JSON object with keys: id, name, start, stages, and optional issues (list of {severity,where,message,resolution}) and confidence.\n"
        "stages have id,name,goal,depends_on(list of stage ids),optional(bool),condition(condition object or null),gates(list of {name,check,on_fail}),tools(list of {tool,key,defaults,note}),skills(list of {skill,enabled:true}).\n"
        "depends_on declares explicit dependencies; a stage runs only after all its dependencies complete. Use ONLY tool/skill names provided above. Keep it executable and practical.\n"
        f"Template name hint: {name or model.summary}\n"
        "Return ONLY the JSON object."
    )
    resp = provider.chat([{"role": "user", "content": prompt}], [])
    data = json.loads(_extract(resp.get("content")))

    template = from_dict(Template, {
        "id": data.get("id") or _slug(data.get("name") or name or "generated"),
        "name": data.get("name") or name,
        "start": data.get("start"),
        "stages": data.get("stages", []),
        "tools": tool_defs,
        "skills": skill_defs,
    })
    validate_template(template)

    report = {
        "source": {"depth": "full"},
        "understood": {
            "summary": model.summary,
            "entrypoints": model.entrypoints,
            "capabilities": model.capabilities,
            "dependencies": model.dependencies,
        },
        "template_preview": to_dict(template),
        "imports": {"tools": [], "skills": []},
        "issues": list(data.get("issues", [])),
        "confidence": data.get("confidence", model.confidence),
        "notes": "",
    }
    return template, report
