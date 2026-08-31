import json
import threading

from lattice_ai.db import JsonStore, connect
from lattice_ai.workspace import ProjectStore


def _sample_evidence(evidence_id: str, run_id: str) -> dict:
    return {
        "id": evidence_id,
        "run_id": run_id,
        "stage_id": "recon",
        "tool": "echo",
        "result": {"value": "x"},
        "created_at": "2026-08-30T00:00:00",
        "hash": "",
    }


def test_json_store_crud(tmp_path):
    store = JsonStore(connect(tmp_path / "t.db"), "evidence")
    store["e1"] = _sample_evidence("e1", "r1")
    store["e2"] = _sample_evidence("e2", "r2")
    assert store["e1"]["run_id"] == "r1"
    assert set(store) == {"e1", "e2"}
    assert len(store) == 2
    assert "e1" in store and "nope" not in store
    assert [v["id"] for v in store.values()] == ["e1", "e2"]  # insertion order
    del store["e1"]
    assert len(store) == 2 - 1


def test_json_store_persists_across_reopen(tmp_path):
    path = tmp_path / "t.db"
    JsonStore(connect(path), "runs")["r1"] = {"id": "r1", "target": "example.com"}
    reopened = JsonStore(connect(path), "runs")
    assert reopened["r1"]["target"] == "example.com"
    assert len(reopened) == 1


def test_json_store_survives_concurrent_writers(tmp_path):
    store = JsonStore(connect(tmp_path / "t.db"), "evidence")
    workers = [
        threading.Thread(target=lambda n=n: [store.__setitem__(f"e-{n}-{i}", _sample_evidence(f"e-{n}-{i}", "r1")) for i in range(25)])
        for n in range(4)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert len(store) == 100


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_project_imports_legacy_json_once(tmp_path):
    root = tmp_path / "projects" / "demo"
    _write(root / "sessions" / "run-a.json", {"id": "run-a", "target": "example.com"})
    _write(root / "sessions" / "run-a.state.json", {"run_id": "run-a"})
    broken = root / "sessions" / "broken.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{not json", encoding="utf-8")  # genuinely malformed
    _write(root / "evidence" / "e1.json", _sample_evidence("e1", "run-a"))
    _write(root / "findings" / "f1.json", {"id": "f1", "title": "SQLi", "severity": "high", "status": "pending"})

    store = ProjectStore(tmp_path / "projects")
    project = store.get("demo")
    assert set(project.runs) == {"run-a"}  # .state.json and broken file skipped
    assert project.evidence["e1"]["run_id"] == "run-a"
    assert project.findings["f1"]["severity"] == "high"
    # legacy files are untouched
    assert (root / "sessions" / "run-a.json").exists()
    assert (root / "evidence" / "e1.json").exists()

    # new writes go to the DB, not new files
    project.save_run("run-b", {"id": "run-b", "target": "example.org"})
    project.save_evidence("e2", _sample_evidence("e2", "run-b"))
    assert not (root / "sessions" / "run-b.json").exists()
    assert not (root / "evidence" / "e2.json").exists()
    assert project.runs["run-b"]["target"] == "example.org"

    # reopening reuses the DB and does not duplicate the import
    reopened = ProjectStore(tmp_path / "projects").get("demo")
    assert set(reopened.runs) == {"run-a", "run-b"}
    assert len(reopened.evidence) == 2
    reopened.save_run("run-a", {"id": "run-a", "target": "updated.example"})
    final = ProjectStore(tmp_path / "projects").get("demo")
    assert final.runs["run-a"]["target"] == "updated.example"
    assert len(final.runs) == 2


def test_project_delete_releases_database(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("temporary")
    project.save_run("r1", {"id": "r1", "target": "example.com"})
    other = store.list()[0]["id"] if store.list()[0]["id"] != "temporary" else store.list()[1]["id"]
    store.switch(other)
    store.delete("temporary")  # must not raise on Windows (open handles)
    assert store.get("temporary") is None


def test_busy_timeout_waits_for_lock_instead_of_raising(tmp_path):
    """M2-A T4: run-teardown writes raced list queries into transient 500s;
    connect() must set busy_timeout so a blocked writer waits, not fails."""
    import time

    db_path = tmp_path / "project.db"
    conn_a = connect(db_path)
    conn_b = connect(db_path)
    store_a = JsonStore(conn_a, "runs")
    store_b = JsonStore(conn_b, "runs")

    conn_a.execute("BEGIN IMMEDIATE")
    conn_a.execute("INSERT INTO runs (id, data) VALUES ('held', '{}')")
    outcome = {}

    def blocked_write():
        started = time.monotonic()
        try:
            store_b["late"] = {"ok": True}
            outcome["waited"] = time.monotonic() - started
        except Exception as exc:  # pragma: no cover - failure path
            outcome["error"] = repr(exc)

    writer = threading.Thread(target=blocked_write)
    writer.start()
    time.sleep(0.3)  # let the second connection hit the held lock
    conn_a.commit()
    writer.join(timeout=10)

    assert not writer.is_alive()
    assert "error" not in outcome, outcome
    assert outcome["waited"] >= 0.2  # it genuinely waited on the lock
    assert store_b["late"] == {"ok": True}


def test_json_store_concurrent_reads_and_writes_are_safe(tmp_path):
    """Regression (M4): reads used the shared SQLite connection without the
    write lock, so concurrent readers + writers raised InterfaceError, tore
    reads (JSONDecodeError / mismatched id) or produced ghost KeyError --
    surfacing as intermittent API 500s on /api/runs and /api/logs. Every
    operation must hold the same lock the writes take; readers must not
    deadlock while a consumer iterates and the writer keeps mutating.
    """
    store = JsonStore(connect(tmp_path / "t.db"), "runs")
    for i in range(50):
        store[f"seed-{i}"] = {"id": f"seed-{i}", "payload": "x" * 2000}

    errors = []
    stop = threading.Event()

    def reader(rid):
        try:
            while not stop.is_set():
                keys = [k for k in store if k.startswith("seed")]
                for k in keys:
                    value = store[k]
                    assert value["id"] == k  # no torn reads
                assert len(store) >= 50  # never-deleted rows stay visible
                assert "seed-0" in store  # no ghost KeyError
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reader{rid}: {type(exc).__name__}: {exc}")
            stop.set()

    def writer(wid):
        try:
            for i in range(300):
                store[f"w{wid}-{i}"] = {"id": f"w{wid}-{i}", "payload": "y" * 2000}
                if i >= 20:
                    del store[f"w{wid}-{i - 20}"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"writer{wid}: {type(exc).__name__}: {exc}")
            stop.set()

    writers = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    readers = [threading.Thread(target=reader, args=(n,)) for n in range(4)]
    for t in writers + readers:
        t.start()
    for t in writers:
        t.join(timeout=60)
    stop.set()
    for t in readers:
        t.join(timeout=30)

    assert not errors, errors
    assert not any(t.is_alive() for t in readers), "readers must stop promptly"
    # 50 seeds, never deleted + 4 writers x the newest 20 keys each
    # (300 writes, then each writer deletes its own older 280).
    assert len(store) == 50 + 4 * 20
    for k, value in store.items():
        assert value["id"] == k

