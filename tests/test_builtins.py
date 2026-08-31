import io
import http.server
import socket
import threading
import urllib.error
import urllib.request

from lattice_ai import builtins
from lattice_ai.builtins import install_builtins
from lattice_ai.tools import ToolRegistry


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/.env":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SECRET=1")
            return
        body = b"<html><title>Demo</title><body><a href='/about'>x</a><script src='/app.js'></script></body></html>"
        self.send_response(200)
        self.send_header("Server", "nginx/1.25")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _start_server(handler=_Handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, "127.0.0.1", port


def test_builtins_registered():
    r = ToolRegistry()
    install_builtins(r)
    names = {t.name for t in r.list_tools()}
    assert {"dnsx", "httpx", "subfinder", "naabu", "nmap", "whatweb", "ffuf", "katana"} <= names


def test_httpx_and_whatweb_and_ffuf_and_katana():
    srv, host, port = _start_server()
    try:
        r = ToolRegistry()
        install_builtins(r)
        base = f"http://{host}:{port}"

        h = r.run("httpx", {"target": base})
        assert h["status"] == 200 and h["server"] == "nginx/1.25" and h["title"] == "Demo"

        w = r.run("whatweb", {"target": base})
        assert w["status"] == 200

        f = r.run("ffuf", {"target": base})
        assert any(p["path"] == "/.env" and p["status"] == 200 for p in f["paths"])

        k = r.run("katana", {"target": base})
        joined = " ".join(k.get("links", []))
        assert "/about" in joined and "/app.js" in joined
    finally:
        srv.shutdown()


def test_naabu_detects_local_open_port():
    srv, host, port = _start_server()
    try:
        r = ToolRegistry()
        install_builtins(r)
        res = r.run("naabu", {"target": host, "ports": [port]})
        assert port in res["open_ports"]
    finally:
        srv.shutdown()


def test_dnsx_resolves_localhost():
    r = ToolRegistry()
    install_builtins(r)
    res = r.run("dnsx", {"target": "localhost"})
    assert res["addresses"]


def test_builtin_never_raises_on_bad_input():
    r = ToolRegistry()
    install_builtins(r)
    assert "error" in r.run("dnsx", {"target": "nonexistent.invalid"})
    assert "error" in r.run("httpx", {"target": "http://127.0.0.1:1"})


def test_ffuf_normalizes_bare_host():
    srv, host, port = _start_server()
    try:
        r = ToolRegistry()
        install_builtins(r)
        res = r.run("ffuf", {"target": f"{host}:{port}"})
        assert any(p["path"] == "/.env" and p["status"] == 200 for p in res["paths"])
    finally:
        srv.shutdown()


class _BlockingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
        elif self.path in ("/.git/HEAD", "/.git/config", "/server-status", "/phpinfo.php", "/.DS_Store"):
            self.send_response(502)
        else:
            self.send_response(404)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_ffuf_separates_blocked_from_found():
    srv, host, port = _start_server(_BlockingHandler)
    try:
        r = ToolRegistry()
        install_builtins(r)
        res = r.run("ffuf", {"target": f"http://{host}:{port}"})
        assert all(p["status"] != 502 for p in res["paths"])
        blocked = {b["path"] for b in res["blocked"]}
        assert {"/.git/HEAD", "/server-status", "/phpinfo.php"} <= blocked
        assert res["blocked_count"] == len(res["blocked"])
    finally:
        srv.shutdown()


class _TechHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            b'<html><head><meta name="generator" content="VSB CMS"></head>'
            b'<body><script src="/system/resource/js/counter.js"></script></body></html>'
        )
        self.send_response(200)
        self.send_header("Server", "nginx")
        self.send_header("X-Powered-By", "PHP/7.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_whatweb_detects_generator_and_cms_markers():
    srv, host, port = _start_server(_TechHandler)
    try:
        r = ToolRegistry()
        install_builtins(r)
        res = r.run("whatweb", {"target": f"http://{host}:{port}"})
        joined = " ".join(res["technologies"])
        assert "generator=VSB CMS" in joined
        assert "vsb-cms" in joined
        assert "server=nginx" in joined
        assert "powered-by=PHP/7.4" in joined
    finally:
        srv.shutdown()


class _FakeResp:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n=-1):
        return self._text.encode("utf-8")


def test_subfinder_falls_back_to_second_source(monkeypatch):
    def fake_urlopen(req, timeout=20):
        url = req.full_url
        if "crt.sh" in url:
            raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
        if "hackertarget.com" in url:
            return _FakeResp("api.example.com,1.2.3.4\nwww.example.com,1.2.3.5\n")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    r = ToolRegistry()
    install_builtins(r)
    res = r.run("subfinder", {"target": "example.com"})
    assert "api.example.com" in res["subdomains"]
    assert res["source"] == "hackertarget"
    assert res["incomplete"] is True


def test_subfinder_dns_fallback_when_http_sources_fail(monkeypatch):
    def fake_urlopen(req, timeout=20):
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)

    def fake_getaddrinfo(host, port):
        if host == "www.example.com":
            return [(2, 1, 6, "", ("1.2.3.4", 0))]
        raise socket.gaierror("not found")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(builtins.socket, "getaddrinfo", fake_getaddrinfo)
    r = ToolRegistry()
    install_builtins(r)
    res = r.run("subfinder", {"target": "example.com"})
    assert res["subdomains"] == ["www.example.com"]
    assert res["source"] == "dns-brute"
    assert res["incomplete"] is True


def test_subfinder_marks_incomplete_when_all_sources_fail(monkeypatch):
    def fake_urlopen(req, timeout=20):
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)

    def fake_getaddrinfo(host, port):
        raise socket.gaierror("not found")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(builtins.socket, "getaddrinfo", fake_getaddrinfo)
    r = ToolRegistry()
    install_builtins(r)
    res = r.run("subfinder", {"target": "example.com"})
    assert res["incomplete"] is True
    assert res["count"] == 0
    assert "502" in res.get("error", "")


def test_naabu_tolerates_bad_ports():
    r = ToolRegistry()
    install_builtins(r)
    res = r.run("naabu", {"target": "127.0.0.1", "ports": ["abc", "notaport"]})
    assert "open_ports" in res
