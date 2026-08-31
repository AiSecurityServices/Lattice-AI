"""Run budget guard: token / cost / tool-call / wall-clock limits.

Modeled after hackingBuddyGPT's unified Limits (rounds/tokens/cost/duration)
and CAI's CAI_PRICE_LIMIT: every dimension is optional (None = unlimited),
each LLM round and tool call feeds the tracker, and exceeding a limit raises
BudgetExceeded so the run layer can wind down gracefully instead of crashing.
"""

import time
from dataclasses import dataclass


@dataclass
class Budget:
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    max_tool_calls: int | None = None
    max_wall_seconds: float | None = None


# Product defaults (template/request-level budgets are a later increment):
# generous enough to never trip an ordinary engagement, tight enough to stop
# a runaway loop.
DEFAULT_BUDGET = Budget(max_tokens=2_000_000, max_tool_calls=500, max_wall_seconds=3600.0)


class BudgetExceeded(Exception):
    def __init__(self, dimension: str, used, limit):
        self.dimension = dimension
        self.used = used
        self.limit = limit
        super().__init__(f"budget exceeded: {dimension} used={used} limit={limit}")


def default_budget() -> Budget:
    return Budget(
        max_tokens=DEFAULT_BUDGET.max_tokens,
        max_cost_usd=DEFAULT_BUDGET.max_cost_usd,
        max_tool_calls=DEFAULT_BUDGET.max_tool_calls,
        max_wall_seconds=DEFAULT_BUDGET.max_wall_seconds,
    )


class BudgetTracker:
    """Counters for one run. Single-threaded: the run loop is the only writer.

    ``check()`` validates every dimension and is meant to run at the top of
    each agent iteration / before each stage; ``add_usage`` records an LLM
    response's usage (None-safe for gateways that don't report it);
    ``add_tool_call`` raises as soon as the call budget is crossed.
    """

    def __init__(self, budget: Budget | None = None, *, clock=time.monotonic,
                 price_per_1k_input: float | None = None, price_per_1k_output: float | None = None):
        self.budget = budget or default_budget()
        self._clock = clock
        self._started = clock()
        self.price_per_1k_input = price_per_1k_input
        self.price_per_1k_output = price_per_1k_output
        self.tokens_used = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.llm_calls = 0
        self.tool_calls = 0
        self.cost_usd = 0.0

    def check(self) -> None:
        budget = self.budget
        if budget.max_wall_seconds is not None:
            elapsed = self._clock() - self._started
            if elapsed > budget.max_wall_seconds:
                raise BudgetExceeded("wall_seconds", round(elapsed, 1), budget.max_wall_seconds)
        if budget.max_tokens is not None and self.tokens_used > budget.max_tokens:
            raise BudgetExceeded("tokens", self.tokens_used, budget.max_tokens)
        if budget.max_cost_usd is not None and self.cost_usd > budget.max_cost_usd:
            raise BudgetExceeded("cost_usd", round(self.cost_usd, 4), budget.max_cost_usd)
        if budget.max_tool_calls is not None and self.tool_calls > budget.max_tool_calls:
            raise BudgetExceeded("tool_calls", self.tool_calls, budget.max_tool_calls)

    def add_usage(self, usage: dict | None, cost: float | None = None) -> None:
        if not usage:
            return
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = usage.get("total_tokens")
        self.tokens_used += int(total) if total is not None else prompt + completion
        # in/out split feeds the per-stage execution records; gateways that
        # only report a total leave both at zero (fields stay present).
        self.tokens_in += prompt
        self.tokens_out += completion
        self.llm_calls += 1
        if cost is None and (self.price_per_1k_input or self.price_per_1k_output):
            cost = prompt / 1000 * (self.price_per_1k_input or 0) + completion / 1000 * (self.price_per_1k_output or 0)
        if cost:
            self.cost_usd += cost

    def add_tool_call(self) -> None:
        self.tool_calls += 1
        if self.budget.max_tool_calls is not None and self.tool_calls > self.budget.max_tool_calls:
            raise BudgetExceeded("tool_calls", self.tool_calls, self.budget.max_tool_calls)

    def snapshot(self) -> dict:
        return {
            "tokens_used": self.tokens_used,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "cost_usd": round(self.cost_usd, 4),
            "elapsed_seconds": round(self._clock() - self._started, 3),
            "limits": {
                "max_tokens": self.budget.max_tokens,
                "max_cost_usd": self.budget.max_cost_usd,
                "max_tool_calls": self.budget.max_tool_calls,
                "max_wall_seconds": self.budget.max_wall_seconds,
            },
        }
