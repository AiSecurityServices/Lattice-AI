def _fp_key(f):
    return f.get("dedup_key") or f"{f.get('title', '')}::{f.get('target', '')}"


def build_run_context(prior_run, findings):
    findings = findings or []
    gate_results = [
        e.get("data") for e in prior_run.get("events", [])
        if e.get("type") in ("gate_block", "gate_blocked")
    ]
    stage_status = {}
    for e in prior_run.get("events", []):
        t, d = e.get("type"), e.get("data") or {}
        if t == "stage_started":
            stage_status[d.get("stage")] = "running"
        elif t == "stage_finished":
            stage_status[d.get("stage")] = "completed"
    return {
        "prior_run_id": prior_run.get("id", ""),
        "prior_findings": [
            {k: f.get(k) for k in ("title", "severity", "status", "confidence", "target", "dedup_key")}
            for f in findings
        ],
        "known_false_positives": sorted({_fp_key(f) for f in findings if f.get("status") == "false_positive"}),
        "prior_gate_results": gate_results,
        "prior_stage_status": stage_status,
    }
