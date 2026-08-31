"""SQLite-backed storage for high-volume run artifacts.

Small, human-editable assets (templates, tools, skills, settings, policies)
stay as JSON files. The machine-written, ever-growing run data (runs,
evidence, findings) lives in a per-project SQLite database: writes become
atomic and transactional, concurrent background runs no longer race on file
contents, and startup no longer loads every project's full history into
memory. Each project keeps its own DB file inside the project directory, so
moving or deleting a project directory still moves all of its data.
"""

import json
import sqlite3
import threading
from collections.abc import MutableMapping
from pathlib import Path


def connect(path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Run teardown writes race with list queries from the API threads; wait on
    # the lock (up to 5s) instead of failing instantly with "database is locked".
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class JsonStore(MutableMapping):
    """A dict-like store of JSON documents backed by one SQLite table.

    Covers the full MutableMapping API (get/set/del/len/contains/iteration)
    so existing code that treats ``project.runs`` / ``project.evidence`` /
    ``project.findings`` as plain dicts keeps working unchanged. Iteration
    order is insertion order (rowid). The single shared connection is
    serialized with one lock for both reads and writes: sharing one SQLite
    connection across threads is only safe when every operation holds the
    lock, so the connection is never used concurrently. WAL mode still
    helps by letting other connections (CLI, separate processes) read and
    write without blocking this one.
    """

    def __init__(self, conn: sqlite3.Connection, table: str):
        self._conn = conn
        self._table = table
        self._lock = threading.Lock()
        with self._lock:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )
            conn.commit()

    def __getitem__(self, key):
        with self._lock:
            row = self._conn.execute(
                f"SELECT data FROM {self._table} WHERE id = ?", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __setitem__(self, key, value):
        data = json.dumps(value, ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {self._table} (id, data) VALUES (?, ?) "
                f"ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (key, data),
            )
            self._conn.commit()

    def __delitem__(self, key):
        with self._lock:
            cur = self._conn.execute(f"DELETE FROM {self._table} WHERE id = ?", (key,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(key)

    def __iter__(self):
        # Materialize under the lock so iteration sees a consistent snapshot;
        # the lock is never held across a yield (a consumer that writes while
        # iterating would otherwise deadlock on this non-reentrant lock).
        with self._lock:
            rows = [row[0] for row in self._conn.execute(f"SELECT id FROM {self._table} ORDER BY rowid")]
        return iter(rows)

    def __len__(self):
        with self._lock:
            return self._conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0]

    def __contains__(self, key):
        with self._lock:
            return (
                self._conn.execute(
                    f"SELECT 1 FROM {self._table} WHERE id = ?", (key,)
                ).fetchone()
                is not None
            )
