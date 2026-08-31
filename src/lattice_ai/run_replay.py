def replay_page(run: dict, after: int = 0, limit: int = 100):
    events = run.get("events", [])
    start = max(0, after)
    end = start + max(1, min(limit, 500))
    page = events[start:end]
    return {
        "run_id": run.get("id", ""),
        "events": page,
        "next_after": end,
        "has_more": end < len(events),
    }
