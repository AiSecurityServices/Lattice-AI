from lattice_ai.asset_extractor import extract_assets_from_facts


def test_extracts_ip_and_port():
    facts = {
        "naabu": {"error": None, "ports": [80, 443]},
        "target": "203.0.113.10",
    }
    assets, _ = extract_assets_from_facts(facts, "r1")
    kinds = {a["kind"] for a in assets}
    assert "ip" in kinds
    assert "port" in kinds


def test_does_not_raise_on_unknown_shape():
    assets, relations = extract_assets_from_facts({"unknown": {"x": 1}}, "r1")
    assert assets == []
    assert relations == []
