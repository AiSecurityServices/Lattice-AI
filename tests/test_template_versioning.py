from lattice_ai.library import TemplateStore


def test_save_versioned_bumps_and_keeps_history(tmp_path):
    store = TemplateStore(tmp_path)
    store.save("t", {"id": "t", "version": 1, "name": "v1"})
    assert store.save_versioned("t", {"id": "t", "version": 1, "name": "v2"}) == 2
    assert store.get("t")["version"] == 2
    assert store.list_history("t") == [1]
    assert store.get_version("t", 1)["name"] == "v1"


def test_rollback_writes_new_version(tmp_path):
    store = TemplateStore(tmp_path)
    store.save("t", {"id": "t", "version": 1, "name": "v1"})
    store.save_versioned("t", {"id": "t", "version": 1, "name": "v2"})
    assert store.rollback("t", 1) == 3
    assert store.get("t")["name"] == "v1"
    assert store.get("t")["version"] == 3


def test_rollback_missing_version_raises(tmp_path):
    store = TemplateStore(tmp_path)
    store.save("t", {"id": "t", "version": 1, "name": "v1"})
    try:
        store.rollback("t", 99)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")
