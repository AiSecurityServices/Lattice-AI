import re
from dataclasses import dataclass

from lattice_ai.models import Tool


CATEGORIES = ("destructive", "data-exfil", "system-control")

_LEVEL_ACTIONS = {
    "strict": {"destructive": "deny", "data-exfil": "ask", "system-control": "deny"},
    "standard": {"destructive": "ask", "data-exfil": "ask", "system-control": "ask"},
    "lenient": {"destructive": "ask", "data-exfil": "allow", "system-control": "allow"},
}

_RULES = [
    ("destructive", "rm-rf", re.compile(r"\brm\s+-rf\b", re.I)),
    ("destructive", "del-recursive", re.compile(r"\bdel\s+/s\b|\bRemove-Item\b.*\b-Recurse\b", re.I)),
    ("destructive", "drop-database", re.compile(r"\bDROP\s+(TABLE|DATABASE)\b|\bTRUNCATE\s+(TABLE\s+)?", re.I)),
    ("destructive", "format-volume", re.compile(r"\bformat\s+[a-zA-Z]:", re.I)),
    ("data-exfil", "sqlmap-dump", re.compile(r"\b--dump\b|\bsqlmap\b.*\bdump\b", re.I)),
    ("data-exfil", "database-dump", re.compile(r"\bmysqldump\b|\bpg_dump\b", re.I)),
    ("data-exfil", "outbound-shell", re.compile(r"\bnc\b.*\s-e\s|\bsocat\b.*EXEC:", re.I)),
    ("data-exfil", "file-transfer-out", re.compile(r"\bscp\s+|\brsync\s+", re.I)),
    ("system-control", "shutdown", re.compile(r"\bshutdown\b|\breboot\b", re.I)),
    ("system-control", "stop-service", re.compile(r"\bsystemctl\s+(stop|disable|mask)\b|\bnet\s+stop\b|\bsc\s+stop\b", re.I)),
    ("system-control", "disable-firewall", re.compile(r"\biptables\s+-F\b|\bufw\s+disable\b", re.I)),
]


@dataclass
class DangerVerdict:
    action: str
    category: str
    rule_id: str
    reason: str


def danger_policy_default() -> dict:
    return {"level": "lenient", "whitelist": []}


def _command_text(tool: Tool, args: dict) -> str:
    command = " ".join(tool.command or [])
    args_text = " ".join(f"{k}={v}" for k, v in args.items())
    return f"{tool.name} {tool.description or ''} {command} {args_text}"


def _detect(tool: Tool, args: dict) -> DangerVerdict | None:
    text = _command_text(tool, args)
    for category, rule_id, pattern in _RULES:
        if pattern.search(text):
            return DangerVerdict(
                action="allow",
                category=category,
                rule_id=rule_id,
                reason=f"matched dangerous pattern {rule_id}",
            )
    return None


def _is_whitelisted(policy: dict, tool: Tool, category: str) -> bool:
    return any(
        item.get("tool") == tool.name and item.get("category") == category
        for item in policy.get("whitelist", [])
    )


def evaluate_danger(policy: dict, tool: Tool, args: dict, run_allowances: set[str] | None = None) -> DangerVerdict:
    policy = policy or danger_policy_default()
    run_allowances = run_allowances or set()
    verdict = _detect(tool, args)
    if verdict is None:
        return DangerVerdict("allow", "", "", "no dangerous pattern matched")

    allowance_key = f"{tool.name}:{verdict.category}"
    if allowance_key in run_allowances or _is_whitelisted(policy, tool, verdict.category):
        verdict.action = "allow"
        verdict.reason = "allowed by run allowance or whitelist"
        return verdict

    level = policy.get("level", "standard")
    actions = _LEVEL_ACTIONS.get(level, _LEVEL_ACTIONS["standard"])
    verdict.action = actions[verdict.category]
    verdict.reason = f"{verdict.category} matched rule {verdict.rule_id} under {level} policy"
    return verdict


def add_whitelist(policy: dict, tool: str, category: str) -> dict:
    policy = dict(policy or danger_policy_default())
    whitelist = list(policy.get("whitelist", []))
    if not any(item.get("tool") == tool and item.get("category") == category for item in whitelist):
        whitelist.append({"id": f"wl-{tool}-{category}", "tool": tool, "category": category})
    policy["whitelist"] = whitelist
    return policy


def remove_whitelist(policy: dict, whitelist_id: str) -> dict:
    policy = dict(policy or danger_policy_default())
    policy["whitelist"] = [item for item in policy.get("whitelist", []) if item.get("id") != whitelist_id]
    return policy
