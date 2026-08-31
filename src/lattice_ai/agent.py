import json

from lattice_ai.budget import BudgetExceeded, BudgetTracker
from lattice_ai.events import EventLog
from lattice_ai.graph import evaluate
from lattice_ai.models import Stage, Template, Tool
from lattice_ai.tools import ToolError, ToolRegistry, redact


_EVIDENCE_TOOL_NAMES = {"record_finding", "record_loot", "record_host"}

# Context budget: accumulated facts and raw tool results can grow without
# bound over a long run; keep prompts within a sane window and keep the most
# recent content (the tail), which is what the current stage builds on.
_MAX_FACTS_CHARS = 24000
_MAX_TOOL_RESULT_CHARS = 12000


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"...[truncated, showing last {limit} chars]\n" + text[-limit:]


def enforce_binding_tier(registry, tool, tier: str) -> None:
    """binding.tier="real" fails loudly instead of silently degrading (T-T3)."""
    if tier != "real":
        return
    from lattice_ai.tools import find_real_executable

    if tool.runner == "cli" and find_real_executable(tool.name) is None:
        raise ToolError(
            f"tool {tool.name!r} is bound with tier=real but the real executable is "
            "missing; install it (ToolsPage one-click install) or relax the binding tier"
        )


def count_tier(result, tier_counts: dict):
    """Pop the registry's _tool_tier marker into the run's tier counters."""
    if isinstance(result, dict) and isinstance(tier_counts, dict):
        tier = result.pop("_tool_tier", None)
        if isinstance(tier, dict) and tier.get("tier") in tier_counts:
            tier_counts[tier["tier"]] += 1
    return result


def _evidence_instruction(allowed: dict) -> str:
    available = sorted(_EVIDENCE_TOOL_NAMES & set(allowed))
    if not available:
        return ""
    names = "、".join(available)
    return (
        f"\n\n证据记录规则（必须遵守）：\n"
        f"- 本阶段可用证据工具：{names}。\n"
        f"- 如果本阶段发现任何风险、漏洞或敏感数据，结束前必须调用 record_finding / record_loot 记录，"
        f"不得带着未记录的证据结束阶段。\n"
        f"- 没有真实发现时不要编造；record_finding 只记录有依据的结论。"
    )


def _prior_context_text(prior_context):
    if not prior_context:
        return ""
    return (
        "\n\nPrior run context:\n"
        f"{_clip_text(json.dumps(prior_context, ensure_ascii=False, default=str), _MAX_FACTS_CHARS)}\n"
        "Use this to avoid repeating known false positives and to respect prior gate results."
    )


def _secret_leaves(secret_paths: set) -> set:
    return {p.rsplit(".", 1)[-1] for p in secret_paths}


def _redact_tool_calls(tool_calls: list, secret_paths: set) -> list:
    leaves = _secret_leaves(secret_paths)
    redacted = []
    for tc in tool_calls:
        args = tc.get("arguments") or {}
        redacted.append({**tc, "arguments": redact(args, [a for a in args if a in leaves])})
    return redacted


def tool_to_function_spec(tool: Tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        },
    }


class StageAgent:
    def __init__(self, provider, registry: ToolRegistry, event_log: EventLog, approver=None, max_iterations: int = 10, skills=None, prior_context=None, budget: BudgetTracker | None = None):
        self.provider = provider
        self.registry = registry
        self.event_log = event_log
        self.approver = approver
        self.max_iterations = max_iterations
        self.skills = skills or {}
        self.prior_context = prior_context
        self.budget = budget
        self.tier_counts = {"real": 0, "sim": 0}

    def run_stage(self, stage: Stage, target: str, facts: dict, *, cwd=None, secret_paths: set = None) -> dict:
        secret_paths = secret_paths if secret_paths is not None else set()
        budget = self.budget
        if budget is None:
            budget = self.budget = BudgetTracker()
        allowed = {}
        bindings = {}
        for binding in stage.tools:
            if not binding.enabled:
                continue
            if binding.condition and not evaluate(binding.condition, facts):
                continue
            allowed[binding.tool] = self.registry.get(binding.tool)
            bindings[binding.tool] = binding

        tool_specs = [tool_to_function_spec(tool_def) for tool_def in allowed.values()]

        goal = f" Goal: {stage.goal}" if stage.goal else ""
        skill_sections = []
        for binding in stage.skills:
            if not binding.enabled:
                continue
            content = self.skills.get(binding.skill, "")
            if content:
                skill_sections.append(f"### Skill: {binding.skill}\n{content}")
        skill_text = "\n\n".join(skill_sections)
        system = f"You are executing stage '{stage.name}'.{goal}\n"
        if skill_text:
            system += f"Skills:\n{skill_text}\n\n"
        system += f"Available facts:\n{_clip_text(json.dumps(facts, ensure_ascii=False, default=str), _MAX_FACTS_CHARS)}"
        system += _evidence_instruction(allowed)
        system += _prior_context_text(self.prior_context)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"target: {target}"},
        ]

        for _ in range(self.max_iterations):
            budget.check()
            response = self.provider.chat(messages, tool_specs)
            budget.add_usage(response.get("usage"))
            tool_calls = response.get("tool_calls") or []
            self.event_log.append(
                "agent_message",
                {
                    "stage": stage.id,
                    "content": response.get("content"),
                    "tool_calls": _redact_tool_calls(tool_calls, secret_paths),
                },
            )
            if not tool_calls:
                break
            messages.append({"role": "assistant", "content": response.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["name"]
                if name not in allowed:
                    raise ToolError(f"agent proposed unbound tool {name!r} for stage {stage.id!r}")
                binding = bindings[name]
                args = {"target": target, **binding.defaults, **(tc.get("arguments") or {})}
                secret_args = [a for a in args if a in _secret_leaves(secret_paths)]
                self.event_log.append(
                    "tool_call",
                    {"stage": stage.id, "tool": name, "args": redact(args, secret_args), "source": "agent"},
                )
                enforce_binding_tier(self.registry, allowed[binding.tool], binding.tier)
                if binding.tier == "sim":
                    result = self.registry.run_sim(name, args, event_log=self.event_log)
                else:
                    result = self.registry.run(name, args, timeout=stage.timeout, cwd=cwd, approver=self.approver, event_log=self.event_log)
                result = count_tier(result, self.tier_counts)
                budget.add_tool_call()
                key = binding.key or name
                facts[key] = result
                for sf in allowed[name].secret_fields:
                    secret_paths.add(f"{key}.{sf}")
                logged_result = redact(result, allowed[name].secret_fields)
                self.event_log.append(
                    "tool_result", {"stage": stage.id, "tool": name, "key": key, "result": logged_result}
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.get("id"), "content": _clip_text(json.dumps(result, ensure_ascii=False, default=str), _MAX_TOOL_RESULT_CHARS)}
                )
        return facts


class WorkflowAgent:
    """High-freedom agent: decides steps/tools across the whole workflow."""

    def __init__(self, provider, registry: ToolRegistry, event_log: EventLog, approver=None, max_iterations: int = 25, prior_context=None, budget: BudgetTracker | None = None):
        self.provider = provider
        self.registry = registry
        self.event_log = event_log
        self.approver = approver
        self.max_iterations = max_iterations
        self.prior_context = prior_context
        self.budget = budget
        self.tier_counts = {"real": 0, "sim": 0}

    def run(self, template: Template, target: str, *, cwd=None) -> dict:
        allowed = {}
        binding_tiers = {}
        for stage in template.stages:
            for b in stage.tools:
                if not b.enabled:
                    continue
                current = binding_tiers.get(b.tool, "any")
                if b.tier == "real" or current == "real":
                    binding_tiers[b.tool] = "real"
                elif b.tier == "sim" and current == "any":
                    binding_tiers[b.tool] = "sim"
        for tool in template.tools:
            try:
                allowed[tool.name] = self.registry.get(tool.name)
            except ToolError:
                continue

        tool_specs = [tool_to_function_spec(tool_def) for tool_def in allowed.values()]

        stages_desc = []
        for i, stage in enumerate(template.stages, 1):
            tools = [b.tool for b in stage.tools if b.enabled]
            goal = f" - {stage.goal}" if stage.goal else ""
            stages_desc.append(f"{i}. {stage.name} (id: {stage.id}){goal}; tools: {tools}")
        workflow_text = "\n".join(stages_desc)

        skills_text = ""
        if template.skills:
            skills_text = "\n".join(f"- {s.name}: {s.content or s.description}" for s in template.skills)

        system = (
            "You are executing a security workflow autonomously.\n"
            "Decide which steps and tools to run, and in what order, using the workflow below as guidance.\n"
            "Only call tools that are provided. Stop when the task is complete.\n\n"
            f"Workflow: {template.name}\n{workflow_text}\n"
        )
        if skills_text:
            system += f"\nSkills:\n{skills_text}\n"
        system += _prior_context_text(self.prior_context)
        system += _evidence_instruction(allowed)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Execute this workflow against target: {target}"},
        ]

        facts = {}
        secret_paths = set()
        budget = self.budget
        if budget is None:
            budget = self.budget = BudgetTracker()
        try:
            for _ in range(self.max_iterations):
                budget.check()
                response = self.provider.chat(messages, tool_specs)
                budget.add_usage(response.get("usage"))
                tool_calls = response.get("tool_calls") or []
                self.event_log.append(
                    "agent_message",
                    {"content": response.get("content"), "tool_calls": _redact_tool_calls(tool_calls, secret_paths)},
                )
                if not tool_calls:
                    break
                messages.append({"role": "assistant", "content": response.get("content"), "tool_calls": tool_calls})
                for tc in tool_calls:
                    name = tc["name"]
                    if name not in allowed:
                        raise ToolError(f"agent proposed unbound tool {name!r}")
                    tool_def = allowed[name]
                    args = {"target": target, **(tc.get("arguments") or {})}
                    secret_args = [a for a in args if a in _secret_leaves(secret_paths)]
                    self.event_log.append(
                        "tool_call", {"tool": name, "args": redact(args, secret_args), "source": "workflow_agent"}
                    )
                    enforce_binding_tier(self.registry, Tool(name=name, runner="cli"), binding_tiers.get(name, "any"))
                    if binding_tiers.get(name, "any") == "sim" and name in self.registry._builtins:
                        result = self.registry.run_sim(name, args, event_log=self.event_log)
                    else:
                        result = self.registry.run(name, args, cwd=cwd, approver=self.approver, event_log=self.event_log)
                    result = count_tier(result, self.tier_counts)
                    budget.add_tool_call()
                    facts[name] = result
                    for sf in tool_def.secret_fields:
                        secret_paths.add(f"{name}.{sf}")
                    self.event_log.append(
                        "tool_result", {"tool": name, "result": redact(result, tool_def.secret_fields)}
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.get("id"), "content": _clip_text(json.dumps(result, ensure_ascii=False, default=str), _MAX_TOOL_RESULT_CHARS)}
                    )
        except BudgetExceeded as exc:
            # Out of budget: record it and wind down normally, the run is not an error.
            self.event_log.append(
                "budget_exceeded",
                {"dimension": exc.dimension, "used": exc.used, "limit": exc.limit},
            )
        return facts
