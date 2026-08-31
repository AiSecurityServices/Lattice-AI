def _diff_by_key(base, head, key):
    b = {x[key]: x for x in base}
    h = {x[key]: x for x in head}
    added = [h[k] for k in h if k not in b]
    removed = [b[k] for k in b if k not in h]
    changed = []
    for k in b.keys() & h.keys():
        if b[k] != h[k]:
            changed.append({"base": b[k], "head": h[k]})
    return {"added": added, "removed": removed, "changed": changed}


def diff_runs(base_run, head_run, base_assets, head_assets, base_findings, head_findings, base_evidence, head_evidence):
    return {
        "base_run_id": base_run.get("id", ""),
        "head_run_id": head_run.get("id", ""),
        "findings": _diff_by_key(base_findings, head_findings, "id"),
        "assets": _diff_by_key(base_assets, head_assets, "natural_key"),
        "evidence": _diff_by_key(base_evidence, head_evidence, "id"),
    }
