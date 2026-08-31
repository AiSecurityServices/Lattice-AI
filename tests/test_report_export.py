from lattice_ai.report_export import build_report_data, export_report


def test_pending_findings_go_to_pending_section():
    run = {"id": "run1", "target": "example.com", "facts": {}}
    evidence = []
    findings = [
        {"id": "f1", "title": "bad", "status": "pending", "evidence_ids": []},
        {"id": "f2", "title": "ok", "status": "confirmed", "evidence_ids": ["e1"]},
    ]
    data = build_report_data(run, evidence, findings, "demo")
    assert data["findings"] == [findings[1]]
    assert data["pending"] == [findings[0]]


def test_export_formats():
    run = {"id": "run1", "target": "example.com", "facts": {}}
    data = export_report(run, [], [], "demo", "json")
    assert '"run_id"' in data
    assert "Example" not in data
