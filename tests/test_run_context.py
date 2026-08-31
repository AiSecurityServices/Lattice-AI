from lattice_ai.run_context import build_run_context


def test_build_run_context_extracts_fp_and_gates():
    prior = {"id": "r0", "events": [
        {"type": "stage_started", "data": {"stage": "recon"}},
        {"type": "gate_block", "data": {"stage": "recon", "gate": "has_endpoints"}},
        {"type": "stage_finished", "data": {"stage": "recon"}},
    ]}
    findings = [
        {"title": "A", "status": "false_positive", "dedup_key": "k1", "target": "x"},
        {"title": "B", "status": "confirmed", "dedup_key": "", "target": "x"},
    ]
    ctx = build_run_context(prior, findings)
    assert ctx["known_false_positives"] == ["k1"]
    assert ctx["prior_gate_results"][0]["gate"] == "has_endpoints"
    assert len(ctx["prior_findings"]) == 2
    assert ctx["prior_stage_status"]["recon"] == "completed"


def test_build_run_context_tolerates_legacy_gate_event_name():
    prior = {"id": "r0", "events": [
        {"type": "gate_blocked", "data": {"stage": "recon", "gate": "has_endpoints"}},
    ]}
    ctx = build_run_context(prior, [])
    assert ctx["prior_gate_results"][0]["gate"] == "has_endpoints"
