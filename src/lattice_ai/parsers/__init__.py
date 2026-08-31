"""Output parsers for real CLI tools (T-U3).

``parse(tool, stdout, stderr, returncode)`` dispatches on the toolchain
registry entry for ``tool.name`` and converts raw CLI output into the facts
contract every downstream consumer (asset ingestion, evidence, LLM context)
shares:

    {
      "summary": "...",          # <= 300 chars, for humans and the LLM
      "items":  [{"type": "domain|url|host|port|finding", "value": "...", ...}],
      "stats":  {"total": N, ...},
      "raw":    "...original stdout..."   # caller truncates after parsing
    }

Parsing never raises: a failure degrades to
``{"summary": "parse failed: <reason>", "raw": ..., "parse_error": reason}``
and the caller records a ``parse_fallback`` event; the run keeps going.
"""
import json
from pathlib import Path

from lattice_ai.models import Tool

_TRUNK = 20000
_SUMMARY_MAX = 300


def _empty_facts(raw: str) -> dict:
    return {"summary": "", "items": [], "stats": {"total": 0}, "raw": raw}


def _failed(reason: str, raw: str) -> dict:
    summary = f"parse failed: {reason}"[:_SUMMARY_MAX]
    return {"summary": summary, "items": [], "stats": {"total": 0}, "raw": raw, "parse_error": reason}


def _clip_summary(text: str) -> str:
    return (text or "").strip()[:_SUMMARY_MAX]


def _truncate_raw(text: str, limit: int = _TRUNK) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _iter_jsonl(stdout: str):
    """Yield decoded JSON objects line by line, skipping non-JSON lines."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict):
            yield row


def _iter_json_documents(stdout: str):
    """Yield JSON documents from output that may be one doc or a JSON array."""
    text = stdout.strip()
    if not text:
        return
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # tolerate JSONL masquerading as json output
        yield from _iter_jsonl(stdout)
        return
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict):
                yield row
    elif isinstance(data, dict):
        yield data


def _stats_for(items: list[dict], extra: dict | None = None) -> dict:
    stats = {"total": len(items)}
    by_type: dict[str, int] = {}
    for item in items:
        by_type[item.get("type", "unknown")] = by_type.get(item.get("type", "unknown"), 0) + 1
    stats.update(by_type)
    if extra:
        stats.update(extra)
    return stats


# ---------------------------------------------------------------------------
# per-tool mappers: rows -> items
# ---------------------------------------------------------------------------

def _first(row: dict, *keys, default=""):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _subfinder_rows(rows):
    items = []
    for row in rows:
        host = str(_first(row, "host", "hostname") or "").strip().lower()
        if host:
            items.append({"type": "domain", "value": host, "source": str(_first(row, "source", default="subfinder"))})
    return items, f"{len(items)} 个子域"


def _httpx_rows(rows):
    items = []
    alive = 0
    for row in rows:
        url = str(_first(row, "url", "matched-at") or "").strip()
        if not url:
            continue
        alive += 1
        item = {
            "type": "url",
            "value": url,
            "status_code": row.get("status_code") or row.get("status-code"),
            "title": row.get("title") or "",
            "tech": row.get("tech") or [],
            "cdn": bool(row.get("cdn")),
            "host": row.get("host") or "",
        }
        items.append(item)
    return items, f"{alive} 个存活 Web 端点"


def _naabu_rows(rows):
    items = []
    seen = set()
    for row in rows:
        host = str(_first(row, "host", "ip") or "").strip()
        port = row.get("port") or row.get("port_number")
        if not host or port is None:
            continue
        key = (host, int(port))
        if key in seen:
            continue
        seen.add(key)
        items.append({"type": "port", "value": f"{host}:{port}", "host": host, "port": int(port)})
    return items, f"{len(seen)} 个开放端口"


def _dnsx_rows(rows):
    items = []
    for row in rows:
        host = str(_first(row, "host") or "").strip().lower()
        if not host:
            continue
        a = row.get("a") or []
        item = {"type": "domain", "value": host, "a_record": [str(v) for v in a] if isinstance(a, list) else [str(a)]}
        if row.get("ttl"):
            item["ttl"] = row["ttl"]
        items.append(item)
    return items, f"{len(items)} 条 DNS A 记录"


def _tlsx_rows(rows):
    items = []
    for row in rows:
        host = str(_first(row, "host") or "").strip()
        port = row.get("port")
        value = f"https://{host}:{port}" if port else (f"https://{host}" if host else "")
        if not value or host in ("", None):
            continue
        items.append({
            "type": "url",
            "value": value,
            "subject_dn": row.get("subject_dn") or "",
            "issuer_dn": row.get("issuer_dn") or "",
            "not_after": row.get("not_after") or "",
        })
    return items, f"{len(items)} 个 TLS 端点"


def _katana_rows(rows):
    items = []
    for row in rows:
        url = str(_first(row, "url", "endpoint") or "").strip()
        if not url:
            continue
        items.append({
            "type": "url",
            "value": url,
            "method": row.get("method") or "GET",
            "source": row.get("source") or "",
            "tag": row.get("tag") or "",
        })
    return items, f"{len(items)} 个爬取到的 URL"


def _gau_lines(lines):
    items = []
    for line in lines:
        url = line.strip()
        if url and "://" in url:
            items.append({"type": "url", "value": url, "source": "gau"})
    return items, f"{len(items)} 个历史 URL"


def _ffuf_rows(rows):
    items = []
    for row in rows:
        results = row.get("results") if isinstance(row.get("results"), list) else None
        if results is not None:
            for hit in results:
                if isinstance(hit, dict):
                    url = str(hit.get("url") or "").strip()
                    if url:
                        items.append({
                            "type": "url",
                            "value": url,
                            "status": hit.get("status"),
                            "length": hit.get("length"),
                            "input": (hit.get("input") or {}).get("FUZZ") if isinstance(hit.get("input"), dict) else "",
                        })
            continue
        url = str(_first(row, "url") or "").strip()
        if url:
            items.append({"type": "url", "value": url, "status": row.get("status"), "length": row.get("length")})
    return items, f"{len(items)} 个 fuzz 命中"


def _nuclei_rows(rows):
    items = []
    severity_count: dict[str, int] = {}
    for row in rows:
        matched = str(_first(row, "matched-at", "matched") or "").strip()
        template_id = row.get("template-id") or row.get("templateID") or ""
        info = row.get("info") or {}
        severity = str(info.get("severity", "info")).lower() if isinstance(info, dict) else "info"
        if not matched and not template_id:
            continue
        severity_count[severity] = severity_count.get(severity, 0) + 1
        items.append({
            "type": "finding",
            "value": matched or str(template_id),
            "template_id": str(template_id),
            "name": (info.get("name") if isinstance(info, dict) else "") or "",
            "severity": severity,
            "cve": [
                cve.get("id") for cve in (info.get("classification", {}) or {}).get("cve-id", []) or []
                if isinstance(cve, dict)
            ] if isinstance(info, dict) and isinstance((info.get("classification", {}) or {}).get("cve-id"), list) else [],
        })
    parts = [f"{k}:{v}" for k, v in sorted(severity_count.items())]
    summary = f"{len(items)} 条漏洞发现" + (f"（{' / '.join(parts)}）" if parts else "")
    return items, summary


def _dalfox_rows(rows):
    items = []
    for row in rows:
        data = str(_first(row, "data", "url") or "").strip()
        if not data:
            continue
        items.append({
            "type": "finding",
            "value": data,
            "msg": row.get("msg") or "",
            "severity": str(row.get("severity", "medium")).lower(),
            "type": "finding",
            "evidence": row.get("evidence") or "",
        })
    return items, f"{len(items)} 条 XSS 发现"


# per-tool mapper modules (kept beside this package's core dispatch)
from lattice_ai.parsers.trivy import trivy_rows as _trivy_rows  # noqa: E402


_ROW_MAPPERS = {
    "subfinder": _subfinder_rows,
    "httpx": _httpx_rows,
    "naabu": _naabu_rows,
    "dnsx": _dnsx_rows,
    "tlsx": _tlsx_rows,
    "katana": _katana_rows,
    "ffuf": _ffuf_rows,
    "nuclei": _nuclei_rows,
    "dalfox": _dalfox_rows,
    "trivy": _trivy_rows,
}

_LINE_MAPPERS = {
    "gau": _gau_lines,
    "waybackurls": _gau_lines,  # same shape: one URL per line
}


def _nmap_parse(stdout: str) -> tuple[list[dict], str]:
    """L3: stream the nmap -oX - XML document into host/port items."""
    import xml.etree.ElementTree as ET

    items: list[dict] = []
    hosts = 0
    parser = ET.XMLPullParser(["start", "end"])
    current_host = None
    in_hosthint = False  # <hosthint><host>... pre-declares hosts; not scan results
    try:
        for chunk in stdout.splitlines(keepends=True):
            parser.feed(chunk)
            for event, element in parser.read_events():
                if element.tag == "hosthint":
                    in_hosthint = event == "start"
                    continue
                if in_hosthint:
                    continue
                if event == "start" and element.tag == "host":
                    current_host = {"addresses": [], "ports": []}
                elif event == "end" and element.tag == "address" and current_host is not None:
                    if element.get("addrtype") in ("ipv4", "ipv6") and element.get("addr"):
                        current_host["addresses"].append(element.get("addr"))
                elif event == "end" and element.tag == "port" and current_host is not None:
                    port_id = element.get("portid")
                    state = element.find("state")
                    if port_id and state is not None and state.get("state") == "open":
                        current_host["ports"].append(int(port_id))
                elif event == "end" and element.tag == "host" and current_host is not None:
                    hosts += 1
                    address = current_host["addresses"][0] if current_host["addresses"] else ""
                    for port in current_host["ports"]:
                        items.append({"type": "port", "value": f"{address}:{port}", "host": address, "port": port})
                    if address:
                        items.append({"type": "host", "value": address, "addresses": current_host["addresses"]})
                    current_host = None
        parser.close()
    except ET.ParseError as exc:
        raise ValueError(f"invalid nmap XML: {exc}") from exc
    summary = f"{hosts} 台主机，{sum(1 for i in items if i['type'] == 'port')} 个开放端口"
    return items, summary


def parse_for_entry(entry, stdout: str, stderr: str, returncode: int) -> dict:
    """Parse stdout according to a registry entry's format/parse level.
    The raw copy in the returned facts is already truncated to _TRUNK."""
    facts = _parse_for_entry(entry, stdout, stderr, returncode)
    facts["raw"] = _truncate_raw(facts.get("raw", stdout))
    return facts


def _parse_for_entry(entry, stdout: str, stderr: str, returncode: int) -> dict:
    if entry.parse_level == "L3":
        if entry.name == "nmap":
            try:
                items, summary = _nmap_parse(stdout)
            except ValueError as exc:
                return _failed(str(exc), stdout)
            return {
                "summary": _clip_summary(summary),
                "items": items,
                "stats": _stats_for(items),
                "raw": stdout,
            }
        return _failed(f"no L3 parser for {entry.name}", stdout)

    if entry.output_format == "text":
        mapper = _LINE_MAPPERS.get(entry.name)
        if mapper is None:
            return _failed(f"no line parser for {entry.name}", stdout)
        items, summary = mapper(stdout.splitlines())
        return {"summary": _clip_summary(summary), "items": items, "stats": _stats_for(items), "raw": stdout}

    # JSON / JSONL (L1)
    rows = list(_iter_jsonl(stdout)) if entry.output_format == "jsonl" else list(_iter_json_documents(stdout))
    if entry.output_format == "json" and stdout.strip() and not rows:
        return _failed("stdout is not valid JSON", stdout)
    if not rows:
        return _empty_facts(stdout)
    mapper = _ROW_MAPPERS.get(entry.name)
    if mapper is None:
        return _failed(f"no mapper for {entry.name}", stdout)
    items, summary = mapper(rows)
    return {"summary": _clip_summary(summary), "items": items, "stats": _stats_for(items), "raw": stdout}


def parse(tool: Tool, stdout: str, stderr: str, returncode: int) -> dict | None:
    """Parse CLI output for a registry tool; None when the tool has no registry
    entry (user recipes keep the legacy whole-output json.loads behaviour)."""
    from lattice_ai.toolchain_registry import get_entry

    entry = get_entry(tool.name)
    if entry is None:
        return None
    return parse_for_entry(entry, stdout or "", stderr or "", returncode)


__all__ = ["parse", "parse_for_entry", "_TRUNK"]
