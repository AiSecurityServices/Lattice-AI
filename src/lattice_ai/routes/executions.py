"""Stage-execution record routes (M3-A E1): per-run rows and cross-run queries."""
from fastapi import APIRouter, HTTPException, Query

from lattice_ai import runtime as rt

router = APIRouter()


@router.get("/api/runs/{run_id}/executions")
def run_executions(run_id: str):
    rt._projects_store()  # lazy-bind the store (M2 lesson: first-hit requests)
    if run_id not in rt._active().runs:
        raise HTTPException(status_code=404, detail="run not found")
    rows = [row for row in rt._active().executions.values() if row.get("run_id") == run_id]
    run = rt._active().runs.get(run_id) or {}
    template = rt._template_store.get(run.get("template_id", ""))
    order = {stage["id"]: index for index, stage in enumerate((template or {}).get("stages", []))}
    rows.sort(key=lambda row: (order.get(row.get("stage_id"), 10_000), row.get("started_at") or ""))
    return {"run_id": run_id, "executions": rows}


@router.get("/api/executions")
def list_executions(
    status: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    rt._projects_store()
    wanted = {part.strip() for part in status.split(",") if part.strip()} if status else None
    items = list(rt._active().executions.values())
    items.reverse()  # newest writes first
    if wanted:
        items = [row for row in items if row.get("status") in wanted]
    return {"executions": items[offset : offset + limit], "total": len(items)}
