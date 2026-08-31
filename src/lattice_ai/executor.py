from copy import deepcopy
from datetime import datetime, timezone
import time

from lattice_ai.budget import BudgetExceeded, BudgetTracker
from lattice_ai.events import EventLog
from lattice_ai.graph import evaluate, resolve_path, validate_template
from lattice_ai.models import RunState, Template
from lattice_ai.run_state import (
    COMPLETED,
    FAILED,
    PENDING,
    READY,
    RUNNING,
    SKIPPED,
    next_ready,
    save_run_state,
    transitive_dependents,
)
from lattice_ai.tools import ToolError, ToolRegistry, redact


def _is_secret_path(fact_path: str, secret_paths: set) -> bool:
    for sp in secret_paths:
        if fact_path == sp or fact_path.startswith(sp + ".") or sp.startswith(fact_path + "."):
            return True
    return False


class Executor:
    def __init__(self, template: Template, registry: ToolRegistry, event_log: EventLog, *, run_id: str = "", checkpoint_path=None, budget: BudgetTracker | None = None, exec_store=None):
        validate_template(template)
        self.template = template
        self.registry = registry
        self.event_log = event_log
        self.run_id = run_id
        self.checkpoint_path = checkpoint_path
        self.budget = budget
        # Optional stage-execution audit store (E1): any MutableMapping keyed
        # by "{run_id}:{stage_id}"; None keeps plain executor runs store-free.
        self.exec_store = exec_store

    def _stage(self, stage_id):
        for s in self.template.stages:
            if s.id == stage_id:
                return s
        raise KeyError(stage_id)

    def run(self, target: str, *, cwd=None, approver=None, agent=None, run_state: RunState | None = None) -> RunState:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rs = run_state or RunState(
            run_id=self.run_id,
            template_id=self.template.id,
            target=target,
            stage_status={s.id: PENDING for s in self.template.stages},
            started_at=now,
            updated_at=now,
        )
        if self.budget is None:
            self.budget = BudgetTracker()
        if agent is not None and getattr(agent, "budget", None) is None:
            # One shared tracker per run: agent LLM rounds and executor tool
            # calls draw on the same budget.
            agent.budget = self.budget
        self.event_log.append("run_started", {"template": self.template.id, "target": target})
        secret_paths = set()
        budget_exceeded = None
        while True:
            ready = next_ready(self.template, rs)
            if ready:
                for sid in ready:
                    rs.current_stage = sid
                    rs.stage_status[sid] = RUNNING
                    stage = self._stage(sid)
                    self.event_log.append("stage_started", {"stage": sid})
                    exec_clock0 = time.monotonic()
                    exec_snap0 = self.budget.snapshot()
                    self._exec_begin(rs.run_id, sid)
                    facts = rs.facts
                    try:
                        if agent is not None:
                            facts = agent.run_stage(stage, target, facts, cwd=cwd, secret_paths=secret_paths)
                        else:
                            facts = self._run_stage_controlled(
                                stage, target, facts, cwd=cwd, approver=approver, secret_paths=secret_paths,
                                tool_tiers=rs.tool_tiers,
                            )
                    except BudgetExceeded as exc:
                        # Not a run failure: record the breach, skip the rest,
                        # and finish normally so the run stays resumable.
                        budget_exceeded = exc
                        self.event_log.append(
                            "budget_exceeded",
                            {"stage": sid, "dimension": exc.dimension, "used": exc.used, "limit": exc.limit},
                        )
                        self._exec_finish(rs.run_id, sid, SKIPPED, exec_clock0, exec_snap0,
                                          error=f"budget_exceeded: {exc.dimension}")
                        break
                    rs.facts = facts
                    blocked, blocked_gates = self._evaluate_gates(stage, rs.facts)
                    if blocked:
                        self._exec_finish(rs.run_id, sid, FAILED, exec_clock0, exec_snap0,
                                          error=f"gate blocked: {', '.join(blocked_gates)}")
                    else:
                        self._exec_finish(rs.run_id, sid, COMPLETED, exec_clock0, exec_snap0)
                    self.event_log.append("stage_finished", {"stage": sid, "status": FAILED if blocked else COMPLETED})
                    rs.stage_status[sid] = FAILED if blocked else COMPLETED
                    rs.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    self._save_checkpoint(rs, secret_paths)
                if budget_exceeded is not None:
                    break
                continue

            # No stage is ready: skip pending stages that can never run so the
            # DAG keeps flowing (condition false, or a dependency failed).
            advanced = False
            for stage in self.template.stages:
                status = rs.stage_status.get(stage.id, PENDING)
                if status != PENDING:
                    continue
                reason = ""
                if stage.condition and not evaluate(stage.condition, rs.facts):
                    reason = "condition_false"
                elif any(rs.stage_status.get(dep) == FAILED for dep in stage.depends_on):
                    reason = "dependency_failed"
                if not reason:
                    continue
                rs.stage_status[stage.id] = SKIPPED
                rs.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.event_log.append(
                    "stage_finished", {"stage": stage.id, "status": SKIPPED, "reason": reason}
                )
                self._exec_skip(rs.run_id, stage.id, reason)
                advanced = True
            if not advanced:
                break
        if budget_exceeded is not None:
            rs.budget_status = "exceeded"  # attached dynamically; persisted by run_state.save_run_state
            for stage in self.template.stages:
                if rs.stage_status.get(stage.id) in (PENDING, READY, RUNNING):
                    rs.stage_status[stage.id] = SKIPPED
                    rs.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    self.event_log.append(
                        "stage_finished", {"stage": stage.id, "status": SKIPPED, "reason": "budget_exceeded"}
                    )
                    self._exec_skip(rs.run_id, stage.id, "budget_exceeded")
            self._save_checkpoint(rs, secret_paths)
        self.event_log.append("run_finished", {"facts": redact(rs.facts, sorted(secret_paths))})
        return rs

    def _enforce_binding_tier(self, binding) -> None:
        """binding.tier="real" fails loudly instead of silently degrading (T-T3)."""
        if binding.tier != "real":
            return
        from lattice_ai.tools import find_real_executable

        tool = self.registry.get(binding.tool)
        if tool.runner == "cli" and find_real_executable(binding.tool) is None:
            raise ToolError(
                f"tool {binding.tool!r} is bound with tier=real but the real executable is "
                "missing; install it (ToolsPage one-click install) or relax the binding tier"
            )

    @staticmethod
    def _count_tier(result, tool_tiers):
        if isinstance(result, dict) and tool_tiers is not None:
            tier = result.pop("_tool_tier", None)
            if isinstance(tier, dict) and tier.get("tier") in tool_tiers:
                tool_tiers[tier["tier"]] += 1
        return result

    def _save_checkpoint(self, rs: RunState, secret_paths: set) -> None:
        if self.checkpoint_path is None:
            return
        checkpoint = deepcopy(rs)
        checkpoint.facts = redact(checkpoint.facts, sorted(secret_paths))
        save_run_state(checkpoint, self.checkpoint_path)
        rs.checkpoint_version = checkpoint.checkpoint_version

    def _evaluate_gates(self, stage, facts: dict) -> tuple[bool, list[str]]:
        blocked = False
        blocked_gates: list[str] = []
        for gate in stage.gates:
            if not gate.check:
                continue
            if evaluate(gate.check, facts):
                continue
            if gate.on_fail == "warn":
                self.event_log.append("gate_warn", {"stage": stage.id, "gate": gate.name})
            else:
                self.event_log.append("gate_block", {"stage": stage.id, "gate": gate.name})
                blocked = True
                blocked_gates.append(gate.name)
        return blocked, blocked_gates

    # ---- stage execution records (M3-A E1) ----

    def _exec_begin(self, run_id: str, stage_id: str) -> None:
        if self.exec_store is None or not run_id:
            return
        self._exec_upsert(run_id, stage_id, {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "finished_at": "",
            "elapsed_ms": 0,
            "tool_calls": 0,
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "error": "",
        })

    def _exec_finish(self, run_id: str, stage_id: str, status: str, clock0: float, snap0: dict, error: str = "") -> None:
        if self.exec_store is None or not run_id:
            return
        snap1 = self.budget.snapshot()
        row = {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "elapsed_ms": max(0, int((time.monotonic() - clock0) * 1000)),
            "tool_calls": snap1["tool_calls"] - snap0["tool_calls"],
            "llm_calls": snap1["llm_calls"] - snap0["llm_calls"],
            "tokens_in": snap1["tokens_in"] - snap0["tokens_in"],
            "tokens_out": snap1["tokens_out"] - snap0["tokens_out"],
            "error": error,
        }
        self._exec_upsert(run_id, stage_id, row)

    def _exec_skip(self, run_id: str, stage_id: str, reason: str) -> None:
        if self.exec_store is None or not run_id:
            return
        key = f"{run_id}:{stage_id}"
        existing = self.exec_store.get(key)
        if existing and existing.get("status") == "running":
            # A begun stage that never finished (budget breach): keep its
            # started_at, zero the counters it never got to record.
            self._exec_upsert(run_id, stage_id, {"status": "skipped", "error": reason})
            return
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.exec_store[key] = {
            "run_id": run_id,
            "stage_id": stage_id,
            "status": "skipped",
            "started_at": "",
            "finished_at": now,
            "elapsed_ms": 0,
            "tool_calls": 0,
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "error": reason,
        }

    def _exec_upsert(self, run_id: str, stage_id: str, row: dict) -> None:
        key = f"{run_id}:{stage_id}"
        merged = {**(self.exec_store.get(key) or {}), **row, "run_id": run_id, "stage_id": stage_id}
        self.exec_store[key] = merged

    def skip_stage(self, rs: RunState, stage_id: str) -> RunState:
        if stage_id not in {s.id for s in self.template.stages}:
            raise KeyError(stage_id)
        rs.stage_status[stage_id] = SKIPPED
        rs.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return rs

    def jump_to(self, rs: RunState, stage_id: str) -> RunState:
        if stage_id not in {s.id for s in self.template.stages}:
            raise KeyError(stage_id)
        rs.current_stage = stage_id
        rs.stage_status[stage_id] = READY
        rs.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return rs

    def revisit_stage(self, rs: RunState, stage_id: str) -> set[str]:
        dependents = transitive_dependents(self.template, stage_id)
        for sid in dependents:
            rs.stage_status[sid] = PENDING
        rs.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return dependents

    def _run_stage_controlled(self, stage, target, facts, *, cwd=None, approver=None, secret_paths=None,
                              tool_tiers=None):
        secret_paths = secret_paths if secret_paths is not None else set()
        for binding in stage.tools:
            if not binding.enabled:
                continue
            if binding.condition and not evaluate(binding.condition, facts):
                continue
            if self.budget is not None:
                self.budget.check()
            args = {"target": target, **binding.defaults}
            injected = {}
            for arg_name, fact_path in binding.args_from.items():
                value = resolve_path(facts, fact_path)
                if value is not None:
                    args[arg_name] = value
                    injected[arg_name] = fact_path
            secret_args = [a for a, p in injected.items() if _is_secret_path(p, secret_paths)]
            self.event_log.append(
                "tool_call", {"stage": stage.id, "tool": binding.tool, "args": redact(args, secret_args)}
            )
            self._enforce_binding_tier(binding)
            if binding.tier == "sim":
                result = self.registry.run_sim(binding.tool, args, event_log=self.event_log)
            else:
                result = self.registry.run(binding.tool, args, timeout=stage.timeout, cwd=cwd,
                                           approver=approver, event_log=self.event_log)
            result = self._count_tier(result, tool_tiers)
            if self.budget is not None:
                self.budget.add_tool_call()
            key = binding.key or binding.tool
            facts[key] = result
            tool_def = self.registry.get(binding.tool)
            for sf in tool_def.secret_fields:
                secret_paths.add(f"{key}.{sf}")
            logged_result = redact(result, tool_def.secret_fields)
            self.event_log.append(
                "tool_result", {"stage": stage.id, "tool": binding.tool, "key": key, "result": logged_result}
            )
        return facts

