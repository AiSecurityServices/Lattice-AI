import ipaddress
import re
from urllib.parse import urlparse

from lattice_ai.assets import natural_key


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _normalize_url(value):
    value = str(value).strip()
    if not re.match(r"^https?://", value):
        value = "http://" + value
    return value


def extract_assets_from_facts(facts: dict, run_id: str):
    assets = []
    relations = []

    for key, result in (facts or {}).items():
        if not isinstance(result, dict):
            continue
        # Tier-agnostic contract (T-U3/U5): real parsers and aligned sims both
        # expose items[] with type/value — ingest them alongside legacy fields.
        for item in result.get("items") or []:
            kind = item.get("type")
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            if kind == "domain":
                assets.append({"kind": "subdomain", "value": value, "source_tool": key})
            elif kind == "url":
                url = _normalize_url(value)
                parsed = urlparse(url)
                if parsed.hostname:
                    assets.append({"kind": "endpoint", "value": url, "source_tool": key})
                    if parsed.port:
                        assets.append({"kind": "port", "value": str(parsed.port), "source_tool": key})
            elif kind == "port":
                assets.append({"kind": "port", "value": value, "source_tool": key})
                if item.get("port") is not None:
                    assets.append({"kind": "port", "value": str(item["port"]), "source_tool": key})
            elif kind == "host":
                assets.append({"kind": "ip" if _is_ip(value) else "subdomain", "value": value, "source_tool": key})
            # "finding" items are findings, not assets
        if key in ("dnsx", "subfinder"):
            for value in _as_list(result.get("subdomains")):
                host = str(value).strip()
                if host:
                    assets.append({"kind": "subdomain", "value": host, "source_tool": key})
            for value in _as_list(result.get("addresses")):
                host = str(value).strip()
                if host:
                    assets.append({"kind": "ip", "value": host, "source_tool": key})
            records = result.get("records")
            if isinstance(records, list):
                for value in records:
                    host = str(value).strip()
                    if host:
                        assets.append({"kind": "subdomain", "value": host, "source_tool": key})
        if key in ("naabu", "nmap"):
            target = str(result.get("target") or facts.get("target") or "")
            if _is_ip(target):
                assets.append({"kind": "ip", "value": target, "source_tool": key})
            for port in _as_list(result.get("ports") or result.get("open_ports")):
                assets.append({"kind": "port", "value": str(port), "source_tool": key})
        if key == "httpx":
            single_url = [result["url"]] if result.get("url") else []
            for value in _as_list(result.get("urls") or result.get("endpoints") or single_url):
                url = _normalize_url(value)
                parsed = urlparse(url)
                if parsed.hostname:
                    assets.append({"kind": "endpoint", "value": url, "source_tool": key})
                    if parsed.port:
                        assets.append({"kind": "port", "value": str(parsed.port), "source_tool": key})
        if key == "whatweb":
            for value in _as_list(result.get("technologies")):
                assets.append({"kind": "technology", "value": str(value), "source_tool": key})
        if key in ("ffuf", "katana"):
            raw = result.get("endpoints") or result.get("paths")
            if raw is None and key == "katana":
                raw = result.get("links")
            for value in _as_list(raw):
                if isinstance(value, dict):
                    value = value.get("path") or value.get("url") or ""
                value = str(value).strip()
                if value:
                    assets.append({"kind": "endpoint", "value": value, "source_tool": key})

    unique = {}
    for asset in assets:
        key = natural_key(asset["kind"], asset["value"])
        unique.setdefault(key, {**asset, "source_run_id": run_id, "evidence_ids": []})
    return list(unique.values()), relations
