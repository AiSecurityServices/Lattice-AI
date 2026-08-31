import json
import re
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

from lattice_ai.agent import StageAgent, WorkflowAgent
from lattice_ai.builtins import install_builtins
from lattice_ai.capability import capability_of, suggest_stage
from lattice_ai.danger import evaluate_danger
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.graph import GraphError, validate_template
from lattice_ai.improve import apply_suggestion
from lattice_ai.library import SkillStore, TemplateStore, ToolStore
from lattice_ai.models import Skill, Stage, Template, Tool, ToolBinding, from_dict, to_dict
from lattice_ai.review import generate_findings, generate_report
from lattice_ai.tool_import import map_target_to_args
from lattice_ai.tools import ToolError, ToolRegistry
from lattice_ai.workspace import ProjectStore
from lattice_ai.tool_import import classify_source, import_tool_source
from lattice_ai.paths import data_root


_DATA_ROOT = data_root()


def _spec(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


def _approved_trial_allowances(tool: Tool, danger_policy: dict, args: dict) -> set[str]:
    """Danger categories the user already confirmed for this trial run.

    A trial is always gated by an explicit user confirmation (the pending
    mutation dialog), which satisfies the danger policy's "ask" level; only
    "deny" actions under the active policy still block the run.
    """
    verdict = evaluate_danger(danger_policy or {}, tool, args)
    if verdict.action == "ask":
        return {f"{tool.name}:{verdict.category}"}
    return set()


def _security_context(registry: ToolRegistry, project, *, run_allowances=None) -> None:
    """Attach the active project's scope and danger policies to a registry.

    Every registry that executes tools must go through this; a bare
    ToolRegistry would silently bypass scope and danger enforcement.
    """
    registry.set_security_context(
        scope_policy=project.scope_policy,
        danger_policy=project.danger_policy,
        run_allowances=run_allowances or [],
    )


def _fetch_url(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "lattice-ai"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")[:20000]


def fetch_source(source: str) -> tuple[str, str]:
    """Return (content, hint) where hint is 'skill', 'tool', or 'unknown'."""
    source = source.strip()
    if source.startswith(("http://", "https://")):
        if "raw.githubusercontent.com" in source or "/raw/" in source:
            return _fetch_url(source), "tool"
        repo = re.search(r"github\.com/([^/\s]+)/([^/\s]+)", source)
        if repo:
            owner, name = repo.group(1), repo.group(2)
            blob = re.search(rf"github\.com/{owner}/{name}/blob/([^/\s]+)/([^\s]+)", source)
            if blob:
                raw = f"https://raw.githubusercontent.com/{owner}/{name}/{blob.group(1)}/{blob.group(2)}"
                return _fetch_url(raw), "tool"
            for branch in ("main", "master"):
                for fname, hint in (("SKILL.md", "skill"), ("README.md", "tool")):
                    try:
                        return _fetch_url(f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{fname}"), hint
                    except Exception:
                        continue
        return _fetch_url(source), "unknown"

    path = Path(source).expanduser()
    if path.is_dir():
        skill_md = path / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text(encoding="utf-8", errors="replace")[:20000], "skill"
        for candidate in sorted(path.glob("*")):
            if candidate.is_file() and candidate.suffix.lower() in (".md", ".py", ".sh", ".yaml", ".yml"):
                return candidate.read_text(encoding="utf-8", errors="replace")[:20000], "tool"
        raise ValueError(f"目录里没找到可导入的内容: {source}")
    if path.is_file():
        hint = "skill" if path.name.upper() == "SKILL.MD" else "tool"
        return path.read_text(encoding="utf-8", errors="replace")[:20000], hint
    raise ValueError(f"路径不存在: {source}")


def generate_asset_draft(provider, source: str, content: str, hint: str) -> dict:
    prompt = (
        "You are importing an asset into a security testing project. Decide whether it is a Skill "
        "(markdown instructions such as SKILL.md) or a Tool (a command-line tool/script). Output ONE JSON object:\n"
        'If Skill: {"type":"skill","data":{"name":"<slug>","description":"<one sentence>","category":"","tags":[],"content":"<full markdown>"}}\n'
        'If Tool: {"type":"tool","data":{"name":"<slug>","description":"<one sentence>","runner":"cli","command":["...", "{target}"],"parameters":{"type":"object","properties":{}}}}\n\n'
        f"Source: {source}\nHint: {hint}\nContent:\n{content[:8000]}\n\nReturn ONLY the JSON object."
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    text = response.get("content") or ""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("provider did not return a JSON object")
    return json.loads(text[start : end + 1])


def generate_template_draft(provider, source: str, content: str, hint: str) -> dict:
    prompt = (
        "You are converting an open-source AI security project into a Lattice AI workflow template.\n"
        "Analyze the project description/skill content and output ONE JSON object representing a Template.\n"
        "Required fields: id (kebab-case), name, start (first stage id), stages, tools, skills.\n"
        "Each stage has id, name, goal, depends_on (list of stage ids), optional, condition, gates, tools, skills. Each tool binding has tool, key, defaults, note.\n"
        "A stage runs only after all its depends_on stages complete. Tools include name, description, runner, command, parameters.\n"
        "Keep it practical and executable; do not invent commands that are not implied by the source.\n\n"
        f"Source: {source}\nHint: {hint}\nContent:\n{content[:12000]}\n\nReturn ONLY the JSON object."
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    text = response.get("content") or ""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("provider did not return a JSON object")
    return json.loads(text[start : end + 1])


class AssistantAgent:
    def __init__(self, provider, store: ProjectStore, event_log: EventLog, template_store=None, tool_store=None, skill_store=None, approver=None, max_iterations: int = 25, template=None):
        self.provider = provider
        self.store = store
        self.template_store = template_store or TemplateStore(_DATA_ROOT / "templates")
        self.tool_store = tool_store or ToolStore(_DATA_ROOT / "tools")
        self.skill_store = skill_store or SkillStore(_DATA_ROOT / "skills")
        self.event_log = event_log
        self.approver = approver
        self.max_iterations = max_iterations
        self.template = template
        self._template_registry = self._build_template_registry()

    def _build_template_registry(self):
        registry = ToolRegistry()
        install_builtins(registry)
        if self.template:
            for tool in self.template.tools:
                registry.register(tool)
        return registry

    def _context(self) -> str:
        project = self.store.active()
        templates = ", ".join(f"{t['id']}({t.get('name')})" for t in self.template_store.list())
        tools = ", ".join(t["name"] for t in self.tool_store.list())
        skills = ", ".join(s["name"] for s in self.skill_store.list())
        return (
            f"Current project: {project.name} (id: {project.id})\n"
            f"Templates: {templates or 'none'}\n"
            f"Tools: {tools or 'none'}\n"
            f"Skills: {skills or 'none'}\n"
            "You can operate on this project through the provided functions."
        )

    def _tool_specs(self, template=None) -> list[dict]:
        string = {"type": "string"}
        array = {"type": "array", "items": {"type": "string"}}
        obj = {"type": "object", "additionalProperties": True}
        specs = [
            _spec("list_templates", "List templates in the current project", {}),
            _spec("get_template", "Get a full template by id", {"template_id": string}, ["template_id"]),
            _spec("list_tools", "List tools in the current project", {}),
            _spec("list_skills", "List skills in the current project", {}),
            _spec("list_projects", "List all projects", {}),
            _spec("generate_template_from_source", "Analyze a URL or local path and produce a template draft", {"source": string}, ["source"]),
            _spec("import_asset", "Import a skill or tool from a URL or local path", {"source": string}, ["source"]),
            _spec("create_skill", "Create a skill", {"name": string, "description": string, "content": string, "category": string}, ["name"]),
            _spec("update_skill", "Update a skill", {"name": string, "description": string, "content": string, "category": string}, ["name"]),
            _spec("delete_skill", "Delete a skill", {"name": string}, ["name"]),
            _spec("save_tool", "Create or update a tool recipe", {"name": string, "description": string, "runner": string, "command": array, "parameters": obj}, ["name"]),
            _spec("delete_tool", "Delete a tool recipe", {"name": string}, ["name"]),
            _spec("bind_tool", "Bind an imported tool to a template stage", {
                "tool": string,
                "template_id": string,
                "stage_id": {"type": "string"},
            }, ["tool", "template_id"]),
            _spec("try_tool", "Trial-run an imported tool against a target", {
                "tool": string,
                "target": string,
            }, ["tool", "target"]),
            _spec("apply_workflow_suggestion", "Apply a workflow improvement suggestion to a template", {
                "template_id": string,
                "suggestion": obj,
            }, ["template_id", "suggestion"]),
            _spec("save_template", "Create or update a full workflow template", {"template_id": string, "template": obj}, ["template_id", "template"]),
            _spec("create_template", "Create a blank template", {"name": string}, ["name"]),
            _spec("rename_template", "Rename a template", {"template_id": string, "name": string}, ["template_id", "name"]),
            _spec("delete_template", "Delete a template", {"template_id": string}, ["template_id"]),
            _spec("run_workflow", "Run a template against a target", {"template_id": string, "target": string, "autonomous": {"type": "boolean"}}, ["template_id", "target"]),
            _spec("create_project", "Create a project", {"name": string}, ["name"]),
            _spec("switch_project", "Switch to another project", {"project_id": string}, ["project_id"]),
            _spec("rename_project", "Rename a project", {"project_id": string, "name": string}, ["project_id", "name"]),
            _spec("delete_project", "Delete a project", {"project_id": string}, ["project_id"]),
            _spec("get_settings", "Get LLM settings", {}),
            _spec("update_settings", "Update LLM settings", {"base_url": string, "model": string, "api_key": string}),
        ]
        tpl = template or self.template
        if tpl:
            from lattice_ai.agent import tool_to_function_spec
            specs.extend(tool_to_function_spec(t) for t in tpl.tools)
        return specs

    def _execute(self, name: str, args: dict) -> dict:
        project = self.store.active()
        if name == "list_templates":
            return {"templates": [{"id": t["id"], "name": t.get("name")} for t in self.template_store.list()]}
        if name == "get_template":
            template = self.template_store.get(args["template_id"])
            if template is None:
                raise ValueError(f"template not found: {args['template_id']}")
            return template
        if name == "list_tools":
            return {"tools": [t["name"] for t in self.tool_store.list()]}
        if name == "list_skills":
            return {"skills": [{"name": s["name"], "description": s.get("description")} for s in self.skill_store.list()]}
        if name == "list_projects":
            return {"projects": self.store.list(), "current": self.store.current}
        if name == "generate_template_from_source":
            source = args["source"]
            content, hint = fetch_source(source)
            draft = generate_template_draft(self.provider, source, content, hint)
            return {"template": draft}
        if name == "import_asset":
            source = args["source"]
            kind = classify_source(source)
            if kind in ("mcp", "script", "description"):
                tools = import_tool_source(self.provider, source)
                for tool in tools:
                    self.tool_store.save(tool.name, to_dict(tool))
                return {"imported": [t.name for t in tools]}
            content, hint = fetch_source(source)
            if hint == "skill":
                draft = generate_asset_draft(self.provider, source, content, hint)
                skill = from_dict(Skill, draft.get("data") or {})
                self.skill_store.save(skill.name, to_dict(skill))
                return {"imported": "skill", "name": skill.name}
            tools = import_tool_source(self.provider, source)
            for tool in tools:
                self.tool_store.save(tool.name, to_dict(tool))
            return {"imported": [t.name for t in tools]}
        if name == "create_skill":
            skill = Skill(name=args["name"], description=args.get("description", ""), category=args.get("category", ""), tags=[], content=args.get("content", ""))
            self.skill_store.save(skill.name, to_dict(skill))
            return {"created": skill.name}
        if name == "update_skill":
            if not any(s["name"] == args["name"] for s in self.skill_store.list()):
                raise ValueError(f"skill not found: {args['name']}")
            skill = Skill(name=args["name"], description=args.get("description", ""), category=args.get("category", ""), tags=[], content=args.get("content", ""))
            self.skill_store.save(skill.name, to_dict(skill))
            return {"updated": skill.name}
        if name == "delete_skill":
            self.skill_store.delete(args["name"])
            return {"deleted": args["name"]}
        if name == "save_tool":
            tool = Tool(name=args["name"], description=args.get("description", ""), runner=args.get("runner", "cli"), command=args.get("command", []), parameters=args.get("parameters", {}))
            self.tool_store.save(tool.name, to_dict(tool))
            return {"saved": tool.name}
        if name == "delete_tool":
            self.tool_store.delete(args["name"])
            return {"deleted": args["name"]}
        if name == "bind_tool":
            tool_data = self.tool_store.get(args["tool"])
            if tool_data is None:
                raise ValueError(f"tool not found: {args['tool']}")
            template_data = self.template_store.get(args["template_id"])
            if template_data is None:
                raise ValueError(f"template not found: {args['template_id']}")
            template = from_dict(Template, template_data)
            stage_id = args.get("stage_id") or suggest_stage(template, capability_of(from_dict(Tool, tool_data)))
            if stage_id is None:
                raise ValueError("template has no stage")
            stage = next((s for s in template.stages if s.id == stage_id), None)
            if stage is None:
                raise ValueError(f"stage not found: {stage_id}")
            if not any(t.name == args["tool"] for t in template.tools):
                template.tools.append(from_dict(Tool, tool_data))
            if not any(b.tool == args["tool"] for b in stage.tools):
                stage.tools.append(ToolBinding(tool=args["tool"]))
            self.template_store.save(template.id, to_dict(template))
            return {"template_id": template.id, "tool": args["tool"], "stage_id": stage_id}
        if name == "try_tool":
            tool_data = self.tool_store.get(args["tool"])
            if tool_data is None:
                raise ValueError(f"tool not found: {args['tool']}")
            tool = from_dict(Tool, tool_data)
            mapped = map_target_to_args(self.provider, tool, args["target"])
            project = self.store.active()
            registry = ToolRegistry()
            _security_context(
                registry,
                project,
                run_allowances=_approved_trial_allowances(tool, project.danger_policy, mapped),
            )
            registry.register(tool)
            result = registry.run(tool.name, mapped, approver=lambda t, a: True)
            facts = {tool.name: result}
            minimal = {"name": "导入工具试运行", "stages": [], "tools": []}
            findings = generate_findings(self.provider, facts, minimal, target=args["target"])
            report = generate_report(self.provider, facts, minimal)
            evidence_id = f"evt_trial_{uuid.uuid4().hex[:8]}"
            self.store.active().save_evidence(evidence_id, {
                "id": evidence_id,
                "run_id": "trial",
                "stage_id": "trial",
                "tool": tool.name,
                "args": mapped,
                "result": result,
                "created_at": "",
                "hash": "",
            })
            for finding in findings:
                finding_id = finding.get("id") or f"F-{uuid.uuid4().hex[:8]}"
                finding["id"] = finding_id
                self.store.active().save_finding(finding_id, finding)
            return {"tool": tool.name, "result": result, "findings": findings, "report": report}
        if name == "apply_workflow_suggestion":
            template_data = self.template_store.get(args["template_id"])
            if template_data is None:
                raise ValueError(f"template not found: {args['template_id']}")
            template = from_dict(Template, template_data)
            updated = apply_suggestion(template, args["suggestion"])
            self.template_store.save(updated.id, to_dict(updated))
            return {"template_id": updated.id, "stages": [s.id for s in updated.stages]}
        if name == "save_template":
            template_id = args["template_id"]
            template = from_dict(Template, args["template"])
            self.template_store.save(template_id, to_dict(template))
            return {"saved": template_id}
        if name == "create_template":
            base = re.sub(r"[^a-z0-9]+", "-", args["name"].lower()).strip("-") or "untitled"
            tpl_id = f"{base}-{uuid.uuid4().hex[:8]}"
            tpl = Template(id=tpl_id, name=args["name"], start="start", stages=[Stage(id="start", name="Start", goal="")], tools=[])
            self.template_store.save(tpl.id, to_dict(tpl))
            return {"created": tpl.id}
        if name == "rename_template":
            if self.template_store.get(args["template_id"]) is None:
                raise ValueError(f"template not found: {args['template_id']}")
            self.template_store.rename(args["template_id"], args["name"])
            return {"renamed": args["template_id"]}
        if name == "delete_template":
            self.template_store.delete(args["template_id"])
            return {"deleted": args["template_id"]}
        if name == "run_workflow":
            return self._run_workflow(args["template_id"], args["target"], args.get("autonomous", False))
        if name == "create_project":
            p = self.store.create(args["name"])
            return {"created": p.id, "name": p.name}
        if name == "switch_project":
            self.store.switch(args["project_id"])
            return {"current": self.store.current}
        if name == "rename_project":
            p = self.store.get(args["project_id"])
            if p is None:
                raise ValueError(f"project not found: {args['project_id']}")
            p.save_meta(args["name"])
            return {"renamed": args["project_id"]}
        if name == "delete_project":
            self.store.delete(args["project_id"])
            return {"deleted": args["project_id"]}
        if name == "get_settings":
            return project.settings
        if name == "update_settings":
            settings = dict(project.settings)
            for key in ("base_url", "model", "api_key"):
                if args.get(key):
                    settings[key] = args[key]
            project.save_settings(settings)
            return {k: settings.get(k) for k in ("base_url", "model")}
        if self.template and any(t.name == name for t in self.template.tools):
            args = args or {}
            self.event_log.append("tool_call", {"tool": name, "args": args, "source": "assistant"})
            result = self._template_registry.run(name, args, approver=self.approver)
            self.event_log.append("tool_result", {"tool": name, "result": result})
            return result
        raise ValueError(f"unknown tool: {name}")

    def _import_asset(self, source: str) -> dict:
        content, hint = fetch_source(source)
        draft = generate_asset_draft(self.provider, source, content, hint)
        asset_type = draft.get("type")
        data = draft.get("data") or {}
        if asset_type == "skill":
            skill = from_dict(Skill, data)
            self.skill_store.save(skill.name, to_dict(skill))
            return {"imported": "skill", "name": skill.name}
        tool = from_dict(Tool, data)
        self.tool_store.save(tool.name, to_dict(tool))
        return {"imported": "tool", "name": tool.name}

    def _run_workflow(self, template_id: str, target: str, autonomous: bool) -> dict:
        template_data = self.template_store.get(template_id)
        if template_data is None:
            raise ValueError(f"template not found: {template_id}")
        template = from_dict(Template, template_data)
        validate_template(template)
        registry = ToolRegistry()
        install_builtins(registry)
        _security_context(registry, self.store.active())
        for tool in template.tools:
            registry.register(tool)
        if autonomous:
            facts = WorkflowAgent(self.provider, registry, self.event_log, approver=self.approver).run(template, target)
        else:
            agent = StageAgent(self.provider, registry, self.event_log, approver=self.approver, skills={s.name: s.content for s in template.skills})
            facts = Executor(template, registry, self.event_log).run(target, approver=self.approver, agent=agent)
        return {"facts": facts}

    def _safe_execute(self, name: str, args: dict) -> tuple[dict | None, str | None]:
        try:
            return self._execute(name, args), None
        except (ToolError, ValueError, GraphError, KeyError) as exc:
            return None, str(exc)

    def _is_destructive(self, name: str, args: dict) -> bool:
        if name in ("delete_tool", "delete_skill", "delete_template", "delete_project"):
            return True
        if name == "save_tool":
            return bool(args.get("name")) and any(t["name"] == args.get("name") for t in self.tool_store.list())
        if name == "update_skill":
            return bool(args.get("name")) and any(s["name"] == args.get("name") for s in self.skill_store.list())
        if name in ("rename_template", "rename_project", "update_settings"):
            return True
        return False

    def _is_mutation(self, name: str) -> bool:
        return name in {
            "import_asset",
            "create_skill",
            "update_skill",
            "delete_skill",
            "save_tool",
            "save_template",
            "delete_tool",
            "bind_tool",
            "try_tool",
            "apply_workflow_suggestion",
            "create_template",
            "rename_template",
            "delete_template",
            "create_project",
            "switch_project",
            "rename_project",
            "delete_project",
            "update_settings",
        }

    def respond(self, message: str, history: list[dict] | None = None, confirm: dict | None = None) -> dict:
        history = history or []
        messages = [{"role": "system", "content": self._context()}]
        messages.append(
            {
                "role": "system",
                "content": (
                    "Before calling any tool that creates, updates, deletes, renames, imports, or switches "
                    "assets, first reply in the assistant content with: 我的理解 / 影响范围 / 变更计划 / 风险提示 / 待确认操作。"
                ),
            }
        )

        if confirm and confirm.get("tool"):
            name = confirm["tool"]
            args = confirm.get("args") or {}
            self.event_log.append("tool_call", {"tool": name, "args": args, "source": "assistant", "confirmed": True})
            result, error = self._safe_execute(name, args)
            self.event_log.append("tool_result", {"tool": name, "result": result, "error": error})
            note = (
                f"The user confirmed the following operation and it has been executed: {name} "
                f"{json.dumps(args, ensure_ascii=False)}. Result: "
                f"{json.dumps({'result': result, 'error': error}, ensure_ascii=False, default=str)}"
            )
            messages.append({"role": "system", "content": note})

        for m in history:
            if isinstance(m, dict) and m.get("content") is not None:
                messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        messages.append({"role": "user", "content": message})

        content = ""
        for _ in range(self.max_iterations):
            response = self.provider.chat(messages, self._tool_specs())
            content = response.get("content") or ""
            tool_calls = response.get("tool_calls") or []
            self.event_log.append("assistant_message", {"role": "assistant", "content": content, "tool_calls": tool_calls})
            if not tool_calls:
                break
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("arguments") or {}
                if self._is_mutation(name):
                    self.event_log.append("assistant_pending", {"tool": name, "args": args})
                    return {"content": content, "pending": {"tool": name, "args": args}}
                self.event_log.append("tool_call", {"tool": name, "args": args, "source": "assistant"})
                result, error = self._safe_execute(name, args)
                self.event_log.append("tool_result", {"tool": name, "result": result, "error": error})
                tool_content = json.dumps({"result": result, "error": error}, ensure_ascii=False, default=str)
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": tool_content})
        return {"content": content}
