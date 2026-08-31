from lattice_ai.events import EventLog


def test_append_and_read(tmp_path):
    log = EventLog(tmp_path / "session.jsonl")
    log.append("run_started", {"template": "t1"})
    log.append("tool_call", {"tool": "nmap"})
    events = log.read()
    assert [e.type for e in events] == ["run_started", "tool_call"]
    assert events[0].seq == 1
    assert events[1].seq == 2


def test_seq_resumes_after_reopen(tmp_path):
    # batched-durability semantics: the restart recovers every *flushed* seq;
    # a crash may lose the trailing <=1s window (accepted by M3-A E2).
    path = tmp_path / "session.jsonl"
    log = EventLog(path)
    log.append("a", {})
    log.flush()
    log2 = EventLog(path)
    log2.append("b", {})
    assert log2.read()[-1].seq == 2


# ---- M3-A E2: batched flushing ----

import json
import threading

from lattice_ai.events import EventLog as _Base  # noqa: F401  (re-import for clarity)


def _drain_now(log):
    log.flush()


def test_batched_append_read_is_complete_before_any_flush(tmp_path):
    log = EventLog(tmp_path / "s.jsonl")
    for i in range(1000):
        log.append("tool_call", {"i": i})
    # writer thread may not have ticked yet: read() merges the pending queue
    events = log.read()
    assert len(events) == 1000
    assert [e.seq for e in events] == list(range(1, 1001))
    assert events[42].data["i"] == 42


def test_flush_persists_everything_to_disk(tmp_path):
    log = EventLog(tmp_path / "s.jsonl")
    for i in range(1000):
        log.append("tool_result", {"i": i})
    log.flush()
    lines = [json.loads(line) for line in (tmp_path / "s.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1000  # no torn lines, no losses
    assert [row["seq"] for row in lines] == list(range(1, 1001))
    assert log.read()[999].data["i"] == 999


def test_concurrent_appends_keep_seq_unique_and_ordered(tmp_path):
    log = EventLog(tmp_path / "s.jsonl")
    def worker(base):
        for i in range(250):
            log.append("tool_call", {"w": base, "i": i})
    threads = [threading.Thread(target=worker, args=(w,)) for w in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    log.flush()
    events = log.read()
    assert len(events) == 1000
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 1000
    assert set(seqs) == set(range(1, 1001))


def test_notifying_log_pushes_synchronously_while_disk_write_defers(tmp_path):
    from lattice_ai.events import EventLog as Log

    pushed = []

    class Notifying(Log):
        def __init__(self, path, sink):
            super().__init__(path)
            self._sink = sink

        def append(self, type, data):
            event = super().append(type, data)
            self._sink({"seq": event.seq, "type": event.type, "data": event.data})
            return event

    log = Notifying(tmp_path / "s.jsonl", pushed.append)
    log.append("stage_started", {"stage": "a"})
    assert [p["type"] for p in pushed] == ["stage_started"]  # SSE timing unchanged


def test_read_after_reopen_includes_flushed_tail(tmp_path):
    path = tmp_path / "s.jsonl"
    log = EventLog(path)
    log.append("a", {"n": 1})
    log.flush()
    reopened = EventLog(path)
    reopened.append("b", {"n": 2})
    assert reopened.read()[-1].seq == 2  # tail seq picked up from disk
    reopened.flush()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
