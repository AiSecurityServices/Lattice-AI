import atexit
import json
import os
import threading
import weakref
from dataclasses import dataclass

# Only the tail of an existing log is scanned to find the last sequence number;
# long-running runs would otherwise re-read the whole file on every start.
_TAIL_BYTES = 65536

# Batched durability (M3-A E2): append() enqueues and returns immediately —
# SSE pushes stay synchronous and seq allocation is unchanged — while a
# per-instance writer thread flushes the queue to disk once per interval.
# A crash may lose the trailing <=interval of events; evidence and the run
# record are built from read(), which merges the pending queue, so nothing
# downstream sees gaps. Writers exit after an idle stretch and are flushed
# at process exit via atexit.
_FLUSH_INTERVAL = 1.0
_WRITER_IDLE_EXIT = 30.0

_instances: "weakref.WeakSet[EventLog]" = weakref.WeakSet()


@dataclass
class SessionEvent:
    seq: int
    type: str
    data: dict


def _flush_all_at_exit():
    for instance in list(_instances):
        try:
            instance.flush()
        except Exception:
            pass


atexit.register(_flush_all_at_exit)


class EventLog:
    def __init__(self, path):
        self.path = path
        self._seq = self._read_last_seq()
        self._pending: list[dict] = []
        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._writer: threading.Thread | None = None
        _instances.add(self)

    def _read_last_seq(self):
        if not self.path.exists():
            return 0
        with self.path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - _TAIL_BYTES))
            tail = fh.read().decode("utf-8", "replace")
        lines = tail.splitlines()
        if size > _TAIL_BYTES and lines:
            # The first line in the window may be torn; drop it.
            lines = lines[1:]
        last = 0
        for line in lines:
            if line.strip():
                try:
                    last = max(last, json.loads(line)["seq"])
                except Exception:
                    continue
        return last

    def append(self, type: str, data: dict) -> SessionEvent:
        with self._lock:
            self._seq += 1
            event = SessionEvent(seq=self._seq, type=type, data=data)
            self._pending.append({"seq": event.seq, "type": event.type, "data": event.data})
        self._ensure_writer()
        return event

    def read(self):
        """Disk lines merged with not-yet-flushed queue entries: a run's
        final read() is complete even when the writer hasn't ticked yet."""
        events = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue  # tolerate a torn final line from a crash
                    events.append(SessionEvent(seq=d["seq"], type=d["type"], data=d["data"]))
        with self._lock:
            pending = list(self._pending)
        if pending:
            on_disk = {event.seq for event in events}
            for item in pending:
                if item["seq"] not in on_disk:
                    events.append(SessionEvent(seq=item["seq"], type=item["type"], data=item["data"]))
            events.sort(key=lambda event: event.seq)
        return events

    def flush(self) -> None:
        """Drain the queue to disk now (run end / process exit / tests)."""
        writer = self._writer
        if writer is not None and writer.is_alive() and writer is not threading.current_thread():
            self._wakeup.set()
            writer.join(timeout=5.0)
        self._drain()

    # ---- writer thread ----

    def _ensure_writer(self):
        writer = self._writer
        if writer is not None and writer.is_alive():
            return
        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()

    def _writer_loop(self):
        idle_ticks = 0
        while True:
            self._wakeup.wait(timeout=_FLUSH_INTERVAL)
            self._wakeup.clear()
            self._drain()
            with self._lock:
                idle = not self._pending
            idle_ticks = idle_ticks + 1 if idle else 0
            if idle_ticks >= _WRITER_IDLE_EXIT / _FLUSH_INTERVAL:
                self._writer = None
                return

    def _drain(self):
        with self._lock:
            batch = self._pending
            self._pending = []
        if not batch:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                for item in batch:
                    fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            # The log file vanished under us (temp dir cleaned up after the
            # run layer already consumed read()); dropping the batch is safe.
            pass
