import json

from lattice_ai.agent import tool_to_function_spec
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.models import Template
from lattice_ai.tools import ToolError, ToolRegistry, redact


RUN_WORKFLOW_SPEC = {
    "type": "function",
    "function": {
        "name": "run_workflow",
        "description": "Execute the full workflow deterministically against a target and return the resulting facts.",
        "parameters": {
            "type": "object",
            "properties": {"target": {"type": "string", "description": "Target IP or domain"}},
            "required": ["target"],
        },
    },
}


def template_context(template: Template) -> str:
    lines = [f"Workflow template: {template.name} (id: {template.id})"]
    if template.summary:
        lines.append("Description:")
        lines.append(template.summary)
    lines.append("Stages (in order):")
    for i, stage in enumerate(template.stages, 1):
        tools = [b.tool for b in stage.tools if b.enabled]
        goal = f" - {stage.goal}" if stage.goal else ""
        lines.append(f"{i}. {stage.name} (id: {stage.id}){goal}; tools: {tools}")
    lines.append("Dependencies (depends_on):")
    for stage in template.stages:
        cond = json.dumps(stage.condition, ensure_ascii=False) if stage.condition else "always"
        lines.append(f"  {stage.id} depends_on {stage.depends_on or ['<none>']} [{cond}]")
    lines.append("Tools:")
    for tool in template.tools:
        lines.append(f"  - {tool.name}: {tool.description}")
    if template.skills:
        lines.append("Skills:")
        for skill in template.skills:
            lines.append(f"  - {skill.name}: {skill.content or skill.description}")
    return "\n".join(lines)


def _secret_leaves(secret_paths: set) -> set:
    return {p.rsplit(".", 1)[-1] for p in secret_paths}


def _redact_tool_calls(tool_calls: list, secret_paths: set) -> list:
    leaves = _secret_leaves(secret_paths)
    redacted = []
    for tc in tool_calls:
        args = tc.get("arguments") or {}
        redacted.append({**tc, "arguments": redact(args, [a for a in args if a in leaves])})
    return redacted


class ChatAgent:
    def __init__(
        self,
        provider,
        template: Template,
        registry: ToolRegistry,
        event_log: EventLog,
        approver=None,
        max_iterations: int = 12,
    ):
        self.provider = provider
        self.template = template
        self.registry = registry
        self.event_log = event_log
        self.approver = approver
        self.max_iterations = max_iterations

    def _system_prompt(self, facts: dict | None = None) -> str:
        facts_block = ""
        if facts:
            facts_block = f"\n\nAvailable facts:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
        return (
            "You are a security testing assistant integrated with a workflow engine.\n"
            "You can answer questions about the workflow and, when the user asks you to act, "
            "call the available tools. Use 'run_workflow' to execute the whole workflow against "
            "a target. Only call tools that are provided.\n\n"
            f"{template_context(self.template)}{facts_block}"
        )

    def _tool_specs(self) -> list[dict]:
        specs = [tool_to_function_spec(t) for t in self.template.tools]
        specs.append(RUN_WORKFLOW_SPEC)
        return specs

    def respond(self, message: str, history: list[dict] | None = None, *, cwd=None, initial_facts: dict | None = None) -> dict:
        history = history or []
        self.event_log.append("chat_message", {"role": "user", "content": message})

        facts = dict(initial_facts or {})
        messages = [{"role": "system", "content": self._system_prompt(facts)}]
        for m in history:
            if isinstance(m, dict) and m.get("content") is not None:
                messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        messages.append({"role": "user", "content": message})

        allowed = {t.name for t in self.template.tools} | {"run_workflow"}
        secret_paths = set()
        content = ""

        for _ in range(self.max_iterations):
            response = self.provider.chat(messages, self._tool_specs())
            content = response.get("content") or ""
            tool_calls = response.get("tool_calls") or []
            self.event_log.append(
                "chat_message",
                {"role": "assistant", "content": content, "tool_calls": _redact_tool_calls(tool_calls, secret_paths)},
            )
            if not tool_calls:
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["name"]
                if name not in allowed:
                    raise ToolError(f"agent proposed unbound tool {name!r}")
                args = tc.get("arguments") or {}
                if name == "run_workflow":
                    target = args.get("target") or message
                    self.event_log.append("tool_call", {"tool": name, "args": args, "source": "chat"})
                    result = self._run_workflow(target, cwd=cwd)
                    facts.update(result)
                    self.event_log.append("tool_result", {"tool": name, "fact_keys": sorted(result.keys())})
                else:
                    result = self._run_tool(name, args, secret_paths, cwd=cwd)
                    facts[name] = result
                messages.append(
                    {"role": "tool", "tool_call_id": tc.get("id"), "content": json.dumps(result, ensure_ascii=False, default=str)}
                )

        return {"content": content, "facts": facts}

    def _run_workflow(self, target: str, *, cwd=None) -> dict:
        executor = Executor(self.template, self.registry, self.event_log)
        return executor.run(target, cwd=cwd, approver=self.approver).facts

    def _run_tool(self, name: str, args: dict, secret_paths: set, *, cwd=None) -> dict:
        tool = self.registry.get(name)
        leaves = _secret_leaves(secret_paths)
        secret_args = [a for a in args if a in leaves]
        self.event_log.append(
            "tool_call", {"tool": name, "args": redact(args, secret_args), "source": "chat"}
        )
        result = self.registry.run(name, args, cwd=cwd, approver=self.approver)
        for sf in tool.secret_fields:
            secret_paths.add(f"{name}.{sf}")
        self.event_log.append("tool_result", {"tool": name, "result": redact(result, tool.secret_fields)})
        return result
