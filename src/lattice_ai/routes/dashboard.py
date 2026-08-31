"""Dashboard aggregation routes: KPI cards with daily sparklines + dual feed."""
from datetime import date, timedelta

from fastapi import APIRouter, Query

from lattice_ai import runtime as rt

router = APIRouter()

_FEED_SIZE = 8


def _day_buckets(days: int) -> list[str]:
    today = date.today()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def _sparkline(dates, buckets: list[str]) -> list[int]:
    counts = {bucket: 0 for bucket in buckets}
    for raw in dates:
        day = str(raw or "")[:10]
        if day in counts:
            counts[day] += 1
    return [counts[bucket] for bucket in buckets]


@router.get("/api/dashboard")
def dashboard(session_id: str = "", days: int = Query(default=7, ge=1, le=30)):
    project = rt._active()
    buckets = _day_buckets(days)

    runs = [r for r in project.runs.values() if not session_id or r.get("session_id", "") == session_id]
    runs.sort(key=lambda r: r.get("created_at") or "")
    findings = [f for f in project.findings.values() if not session_id or f.get("session_id", "") == session_id]
    assets = project.assets.list_assets(session_id=session_id)
    subdomains = [a for a in assets if a.get("kind") == "subdomain"]

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for finding in findings:
        key = str(finding.get("severity", "medium"))
        severity_counts[key] = severity_counts.get(key, 0) + 1

    run_created = {r.get("id"): r.get("created_at") or "" for r in runs}
    kpis = {
        "assets": {
            "total": len(assets),
            "spark": _sparkline([a.get("first_seen") for a in assets], buckets),
        },
        "subdomains": {
            "total": len(subdomains),
            "spark": _sparkline([a.get("first_seen") for a in subdomains], buckets),
        },
        "findings": {
            "total": len(findings),
            "severity": severity_counts,
            "spark": _sparkline([f.get("created_at") or run_created.get(f.get("run_id"), "") for f in findings], buckets),
        },
        "runs": {
            "total": len(runs),
            "spark": _sparkline([r.get("created_at") for r in runs], buckets),
        },
    }

    recent_runs = [
        {
            "id": r.get("id"),
            "template_id": r.get("template_id"),
            "target": r.get("target"),
            "kind": r.get("kind", "run"),
            "created_at": r.get("created_at"),
        }
        for r in runs[-_FEED_SIZE:][::-1]
    ]
    recent_findings = [
        {
            "id": f.get("id"),
            "title": f.get("title"),
            "severity": f.get("severity", "medium"),
            "status": f.get("status", "pending"),
            "target": f.get("target"),
            "run_id": f.get("run_id"),
            "created_at": f.get("created_at") or run_created.get(f.get("run_id"), ""),
        }
        for f in findings[-_FEED_SIZE:][::-1]
    ]

    return {
        "session_id": session_id,
        "days": buckets,
        "kpis": kpis,
        "recent_runs": recent_runs,
        "recent_findings": recent_findings,
    }
