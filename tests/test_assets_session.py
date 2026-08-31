from lattice_ai.assets import AssetStore


def test_asset_scoped_by_session(tmp_path):
    s = AssetStore(tmp_path)
    s.upsert_asset(kind="domain", value="a.com", session_id="s1")
    s.upsert_asset(kind="domain", value="b.com", session_id="s2")
    assert [a["value"] for a in s.list_assets(session_id="s1")] == ["a.com"]
    assert len(s.list_assets(session_id="s2")) == 1


def test_asset_graph_scoped_by_session(tmp_path):
    s = AssetStore(tmp_path)
    s.upsert_asset(kind="domain", value="a.com", session_id="s1")
    s.upsert_asset(kind="domain", value="b.com", session_id="s2")
    graph = s.graph(session_id="s1")
    assert [n["value"] for n in graph["nodes"]] == ["a.com"]
