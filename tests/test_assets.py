from lattice_ai.assets import AssetStore, natural_key


def test_natural_key_is_stable():
    assert natural_key("domain", "example.com") == "domain:example.com"


def test_upsert_asset_merges_evidence(tmp_path):
    store = AssetStore(tmp_path)
    store.upsert_asset(kind="domain", value="example.com", source_run_id="r1", source_tool="subfinder", evidence_id="e1")
    store.upsert_asset(kind="domain", value="example.com", source_run_id="r2", source_tool="subfinder", evidence_id="e2")
    assets = store.list_assets()
    assert len(assets) == 1
    assert assets[0]["evidence_ids"] == ["e1", "e2"]
    assert assets[0]["last_seen"] >= assets[0]["first_seen"]


def test_relation_upsert_dedupes(tmp_path):
    store = AssetStore(tmp_path)
    a = store.upsert_asset(kind="domain", value="example.com")
    b = store.upsert_asset(kind="ip", value="203.0.113.10")
    store.upsert_relation(a["id"], b["id"], "resolves_to")
    store.upsert_relation(a["id"], b["id"], "resolves_to")
    assert len(store.list_relations()) == 1
