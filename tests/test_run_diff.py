from lattice_ai.run_diff import diff_runs


def test_diff_returns_added_asset():
    diff = diff_runs(
        {"id": "b"}, {"id": "h"},
        [{"natural_key": "domain:example.com", "value": "example.com"}],
        [{"natural_key": "domain:example.com", "value": "example.com"}, {"natural_key": "ip:203.0.113.10", "value": "203.0.113.10"}],
        [], [], [], [],
    )
    assert diff["assets"]["added"][0]["value"] == "203.0.113.10"
