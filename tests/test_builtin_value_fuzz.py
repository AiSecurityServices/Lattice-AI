from lattice_ai.builtins import _value_fuzz


def test_value_fuzz_injects_pool_value_into_path_param():
    result = _value_fuzz({
        "endpoints": [{"url": "/api/user/{id}", "method": "GET", "params": ["id"]}],
        "pool": [{"key": "id", "value": 1001}],
    })
    probe = next(p for p in result["probes"] if p["endpoint"] == "/api/user/{id}")
    assert probe["param"] == "id"
    assert probe["value"] == 1001
    assert probe["method"] == "GET"


def test_value_fuzz_matches_query_params_and_defaults_method():
    result = _value_fuzz({
        "endpoints": [{"url": "/api/orders?userId=", "method": "", "params": ["userId"]}],
        "pool": [{"key": "userId", "value": "u-42"}],
    })
    assert result["probes"][0]["method"] == "GET"
    assert result["probes"][0]["value"] == "u-42"


def test_value_fuzz_skips_unrelated_pool_entries():
    result = _value_fuzz({
        "endpoints": [{"url": "/api/user", "method": "POST", "params": ["orgId"]}],
        "pool": [{"key": "id", "value": 1001}],
    })
    assert result["probes"] == []
