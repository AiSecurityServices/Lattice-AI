from lattice_ai.models import Template


class GraphError(Exception):
    pass


def resolve_path(data: dict, path: str):
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def evaluate(condition, facts: dict) -> bool:
    if not condition:
        return True
    op = condition.get("op")
    if op == "truthy":
        return bool(resolve_path(facts, condition["key"]))
    if op == "equals":
        return resolve_path(facts, condition["key"]) == condition.get("value")
    if op == "in":
        return resolve_path(facts, condition["key"]) in condition.get("values", [])
    if op == "not":
        return not evaluate(condition.get("condition"), facts)
    if op == "and":
        return all(evaluate(c, facts) for c in condition.get("conditions", []))
    if op == "or":
        return any(evaluate(c, facts) for c in condition.get("conditions", []))
    raise GraphError(f"unknown condition op: {op}")


def validate_template(template: Template) -> None:
    ids = [s.id for s in template.stages]
    if len(ids) != len(set(ids)):
        raise GraphError("duplicate stage id")
    if template.start not in ids:
        raise GraphError(f"start stage {template.start!r} not found")
    for s in template.stages:
        for dep in s.depends_on:
            if dep not in ids:
                raise GraphError(f"stage {s.id} depends on unknown stage {dep!r}")
    _reject_cycles(template)


def _reject_cycles(template: Template) -> None:
    adj = {s.id: list(s.depends_on) for s in template.stages}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s.id: WHITE for s in template.stages}

    def visit(n):
        color[n] = GRAY
        for m in adj[n]:
            if color[m] == GRAY:
                raise GraphError(f"cycle detected at {m!r}")
            if color[m] == WHITE:
                visit(m)
        color[n] = BLACK

    for n in adj:
        if color[n] == WHITE:
            visit(n)
