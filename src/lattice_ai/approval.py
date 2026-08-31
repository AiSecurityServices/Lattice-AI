"""Durable tool-approval records.

Approval state used to live in a process-local dict, so a server restart lost
every pending approval and left anything waiting on a decision stuck forever.
Records now persist in the active project's SQLite store (table ``approvals``),
pending approvals carry a TTL, and denials stay in the store as audit
evidence. ``create_pending`` / ``resolve_pending`` / ``get_pending`` keep
their original signatures so callers are unaffected.

Redaction rule: the persisted record only carries ``args_redacted`` — raw
arguments stay in a process-local map (they are needed to actually run the
approved call) and never reach the store.
"""

import re
import threading
import time
import uuid
from datetime import datetime

from lattice_ai.danger import danger_policy_default, evaluate_danger
from lattice_ai.models import Tool, from_dict
from lattice_ai.tools import ApprovalDenied, redact

DEFAULT_TTL_SECONDS = 24 * 3600
_POLL_INTERVAL = 0.5

# Keys that always count as credentials when redacting args for storage.
_SENSITIVE_KEY = re.compile(
    r"password|passwd|secret|token|api_?key|authorization|cookie|credential|private_?key|access_?key",
    re.I,
)

_store = None  # active project's approvals JsonStore; None = in-memory fallback
_memory: dict = {}
# Raw args / tool payload, intentionally never persisted (may contain secrets).
_raw: dict = {}
_lock = threading.Lock()


def bind_store(store) -> None:
    """Point the module at the active project's approvals store.

    ``None`` falls back to the legacy in-memory dict (used by bare unit tests
    and before a project store exists).
    """
    global _store
    _store = store


def _records():
    return _store if _store is not None else _memory


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _redact_args(args: dict, tool: dict | None) -> dict:
    leaves = {str(p).rsplit(".", 1)[-1] for p in ((tool or {}).get("secret_fields") or [])}
    args = args or {}
    paths = [k for k in args if k in leaves or _SENSITIVE_KEY.search(str(k))]
    return redact(args, paths)


def _classify(tool_name: str, args: dict, tool: dict | None) -> tuple[str, str]:
    """Best-effort danger classification for the audit record; never fails."""
    try:
        payload = dict(tool or {})
        payload.setdefault("name", tool_name)
        verdict = evaluate_danger(danger_policy_default(), from_dict(Tool, payload), args or {})
        return verdict.category or "", verdict.rule_id or ""
    except Exception:
        return "", ""


def create_pending(tool_name: str, args: dict, tool: dict | None = None) -> str:
    approval_id = uuid.uuid4().hex
    args = args or {}
    category, rule_id = _classify(tool_name, args, tool)
    record = {
        "id": approval_id,
        "run_id": "",
        "stage_id": "",
        "tool": tool_name,
        "args_redacted": _redact_args(args, tool),
        "category": category,
        "rule_id": rule_id,
        "policy_level": "",
        "status": "pending",
        "reason": "",
        "created_at": _now_iso(),
        "expires_at": time.time() + DEFAULT_TTL_SECONDS,
        "resolved_at": None,
    }
    with _lock:
        _raw[approval_id] = {"args": args, "tool_payload": tool}
        _records()[approval_id] = record
    return approval_id


def _get_record(approval_id: str) -> dict:
    """Load a record under lock, lazily expiring it when past its TTL."""
    records = _records()
    if approval_id not in records:
        raise KeyError(approval_id)
    item = records[approval_id]
    if item.get("status") == "pending" and time.time() > float(item.get("expires_at") or 0):
        item = {
            **item,
            "status": "expired",
            "reason": item.get("reason") or "approval expired",
            "resolved_at": _now_iso(),
        }
        records[approval_id] = item
    return item


def resolve_pending(approval_id: str, approved: bool, reason: str = "") -> dict:
    with _lock:
        item = _get_record(approval_id)
        if item.get("status") != "pending":
            # Expired or already-resolved approvals cannot be decided anymore.
            raise KeyError(approval_id)
        item = {
            **item,
            "status": "approved" if approved else "denied",
            "reason": reason,
            "resolved_at": _now_iso(),
        }
        _records()[approval_id] = item
        return item


def get_pending(approval_id: str) -> dict:
    with _lock:
        item = dict(_get_record(approval_id))
    raw = _raw.get(approval_id)
    if raw is not None:
        item["args"] = raw.get("args") or {}
        if raw.get("tool_payload") is not None:
            item["tool_payload"] = raw["tool_payload"]
    return item


def wait_pending(approval_id: str, timeout: float | None = None) -> dict:
    """Poll the store until the approval resolves; raises ApprovalDenied on
    denial, TTL expiry, or when ``timeout`` elapses first."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        try:
            item = get_pending(approval_id)
        except KeyError:
            raise ApprovalDenied(f"approval {approval_id} not found")
        status = item.get("status")
        if status == "approved":
            return item
        if status in ("denied", "expired"):
            raise ApprovalDenied(f"approval {approval_id} {status}: {item.get('reason') or 'no reason given'}")
        if deadline is not None and time.monotonic() >= deadline:
            raise ApprovalDenied(f"approval {approval_id} not resolved within timeout")
        time.sleep(_POLL_INTERVAL)


def expire_run_pending(run_id: str) -> int:
    """Expire every still-pending approval of a run (called when the run stops
    or finishes) so no decision hangs after the run is gone."""
    if not run_id:
        return 0
    count = 0
    with _lock:
        records = _records()
        for key in list(records):
            item = records[key]
            if item.get("run_id") == run_id and item.get("status") == "pending":
                records[key] = {
                    **item,
                    "status": "expired",
                    "reason": item.get("reason") or "run finished",
                    "resolved_at": _now_iso(),
                }
                count += 1
    return count
