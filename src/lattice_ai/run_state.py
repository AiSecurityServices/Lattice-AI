import json
from pathlib import Path

from lattice_ai.graph import evaluate
from lattice_ai.models import RunState, Template, from_dict, to_dict
from lattice_ai.persistence import atomic_write_json


PENDING, READY, RUNNING, COMPLETED, SKIPPED, FAILED = (
    "pending", "ready", "running", "completed", "skipped", "failed",
)


def transitive_dependents(template: Template, stage_id: str) -> set[str]:
    dependents = {stage_id}
    changed = True
    while changed:
        changed = False
        for s in template.stages:
            if s.id not in dependents and any(d in dependents for d in s.depends_on):
                dependents.add(s.id)
                changed = True
    return dependents


def stage_ready(template: Template, rs: RunState, s) -> bool:
    if rs.stage_status.get(s.id, PENDING) not in (PENDING, READY):
        return False
    if not all(rs.stage_status.get(d) in (COMPLETED, SKIPPED) for d in s.depends_on):
        return False
    if s.condition and not evaluate(s.condition, rs.facts):
        return False
    return True


def next_ready(template: Template, rs: RunState) -> list[str]:
    out = []
    for s in template.stages:
        if stage_ready(template, rs, s):
            out.append(s.id)
    return out


def save_run_state(rs: RunState, path: Path) -> None:
    rs.checkpoint_version += 1
    data = to_dict(rs)
    # budget_status is attached dynamically by the executor (models.RunState is
    # the shared schema, so the field rides on the checkpoint payload instead).
    budget_status = getattr(rs, "budget_status", "")
    if budget_status:
        data["budget_status"] = budget_status
    atomic_write_json(path, data)


def load_run_state(path: Path) -> RunState:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rs = from_dict(RunState, data)
    if data.get("budget_status"):
        rs.budget_status = data["budget_status"]
    return rs
