"""T-U5: sim outputs expose the same items[]/stats/summary contract as the
real-tool parsers, so downstream (args_from/asset_extractor/gates) is
tier-agnostic. All offline: local HTTP server + patched network fns."""
import socket

import http.server
import threading

from lattice_ai import builtins
from lattice_ai.asset_extractor import extract_assets_from_facts


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><title>Demo</title><body><a href='/about'>x</a></body></html>"
        self.send_response(200)
        self.send_header("Server", "nginx/1.25")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _start_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"127.0.0.1:{port}"


def _shape(result: dict, min_items: int = 1):
    assert isinstance(result.get("items"), list) and len(result["items"]) >= min_items
    assert result["stats"]["total"] == len(result["items"])
    assert isinstance(result["summary"], str) and result["summary"]
    for item in result["items"]:
        assert item["type"] in ("domain", "url", "host", "port", "finding")
        assert item["value"]


def test_subfinder_sim_items(monkeypatch):
    monkeypatch.setattr(builtins, "_crt_sh", lambda t: {"api.example.com"})
    monkeypatch.setattr(builtins, "_hackertarget", lambda t: set())
    result = builtins._subfinder({"target": "example.com"})
    _shape(result, 1)
    assert result["items"][0] == {"type": "domain", "value": "api.example.com", "source": "crt.sh"}
    assert result["subdomains"] == ["api.example.com"]  # legacy field preserved


def test_naabu_and_nmap_sim_items():
    srv, target = _start_server()
    host = "127.0.0.1"
    try:
        for sim in (builtins._naabu, builtins._nmap):
            result = sim({"target": host, "ports": [srv.server_address[1]]})
            _shape(result, 1)
            assert result["items"][0]["type"] == "port"
            assert result["open_ports"] == [srv.server_address[1]]  # legacy field preserved
    finally:
        srv.shutdown()


def test_dnsx_sim_items(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [
        (2, 1, 6, "", ("93.184.216.34", 0)),
        (2, 1, 6, "", ("93.184.216.35", 0)),
    ])
    result = builtins._dnsx({"target": "example.com"})
    _shape(result, 1)
    assert result["items"][0] == {"type": "domain", "value": "example.com",
                                   "a_record": ["93.184.216.34", "93.184.216.35"]}


def test_httpx_sim_items():
    srv, target = _start_server()
    try:
        result = builtins._httpx({"target": target})
        _shape(result, 1)
        item = result["items"][0]
        assert item["type"] == "url" and item["status_code"] == 200 and item["title"] == "Demo"
        assert result["status"] == 200 and result["server"] == "nginx/1.25"  # legacy preserved
    finally:
        srv.shutdown()


def test_ffuf_sim_items():
    srv, target = _start_server()
    try:
        result = builtins._ffuf({"target": "http://" + target + "/.env"})
        _shape(result, 0)
        for item in result["items"]:
            assert item["type"] == "url"
    finally:
        srv.shutdown()


def test_katana_sim_items():
    srv, target = _start_server()
    try:
        result = builtins._katana({"target": target})
        _shape(result, 1)
        assert result["items"][0]["type"] == "url"
        assert result["links"]  # legacy field preserved
    finally:
        srv.shutdown()


def test_nuclei_sim_finding_items():
    srv, target = _start_server()
    try:
        result = builtins._nuclei({"target": "http://" + target + "/.env"})
        _shape(result, 1)
        finding = result["items"][0]
        assert finding["type"] == "finding" and finding["severity"] == "info"
        assert finding["template_id"] == "exposed-path"
    finally:
        srv.shutdown()


def test_dalfox_and_sqlmap_sim_finding_items():
    result = builtins._dalfox({"target": "http://t/?q=x"})
    _shape(result, 0)
    result = builtins._sqlmap({"target": "http://t/?id=1"})
    _shape(result, 0)


def test_asset_extractor_consumes_items_contract():
    facts = {
        "subfinder": {"items": [{"type": "domain", "value": "api.example.com"}]},
        "naabu": {"items": [{"type": "port", "value": "10.0.0.7:443", "port": 443}]},
        "httpx": {"items": [{"type": "url", "value": "https://api.example.com"}]},
        "nuclei": {"items": [{"type": "finding", "value": "http://t/x"}]},
    }
    assets, _ = extract_assets_from_facts(facts, "run-1")
    kinds = sorted((a["kind"], a["value"]) for a in assets)
    assert ("subdomain", "api.example.com") in kinds
    assert ("port", "443") in kinds
    assert ("endpoint", "https://api.example.com") in kinds
    assert all(kind != "finding" for kind, _ in kinds)
