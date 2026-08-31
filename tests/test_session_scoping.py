from lattice_ai.models import Evidence, Finding, from_dict, to_dict


def test_finding_evidence_carry_session_id():
    f = from_dict(Finding, {"id": "f1", "title": "t", "session_id": "conv_1"})
    e = from_dict(Evidence, {"id": "e1", "run_id": "r1", "stage_id": "s", "tool": "t", "session_id": "conv_1"})
    assert f.session_id == "conv_1"
    assert e.session_id == "conv_1"
    assert to_dict(f)["session_id"] == "conv_1"
