"""Builtin tools available by name to all templates.

Templates reference builtin tools by name only; the function bodies live here.
All recon tools are read-only, non-destructive, timeout-bounded and never raise.
"""
import base64
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from lattice_ai.tools import ToolRegistry, _BUILTIN_SPECS, register_tool

_UA = "lattice-ai"

_COMMON_SUBDOMAINS = [
    "www", "mail", "smtp", "pop", "imap", "ftp", "vpn", "oa", "ehall", "jwc",
    "xsc", "lib", "bbs", "news", "ns1", "ns2", "mx", "api", "app", "m", "portal",
    "sso", "login", "crm", "erp", "hr", "old", "static", "img", "cdn", "download",
    "docs", "blog", "forum", "shop", "pay",
]

_CMS_MARKERS = [
    ("wordpress", ("/wp-content/", "/wp-includes/", "wp-json")),
    ("thinkphp", ("thinkphp", "/index.php?s=")),
    ("dedecms", ("dedecms", "powered by dedecms")),
    ("discuz", ("discuz", "comsenz")),
    ("typecho", ("typecho",)),
    ("vsb-cms", ("_sitegray", "index.vsb.css", "system/resource/js", "vsb")),
    ("shiro", ("rememberme=deleteme",)),
]

_CVE_RULES = [
    (re.compile(r"log4j.*2\.(1[0-6]|14\.1)"), "Log4Shell", ["CVE-2021-44228", "CVE-2021-45046"]),
    (re.compile(r"shiro.*1\.(2\.4|2\.5|2\.6)"), "Shiro 反序列化", ["CVE-2016-4437"]),
    (re.compile(r"fastjson.*1\.2\.(2[0-9]|3[0-9]|4[0-7])"), "Fastjson RCE", ["CVE-2017-18349"]),
    (re.compile(r"spring.?boot.*2\.[0-5]\.\d"), "Spring Boot Actuator", ["CVE-2018-1273"]),
    (re.compile(r"struts2?.*2\.[0-3]\.(1[0-9]|2[0-9]|3[0-3])"), "Struts2 RCE", ["CVE-2017-5638"]),
]


def _fetch(url, timeout=8):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(16384).decode("utf-8", "replace")
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.geturl(), resp.status, headers, body


def _url_for(target):
    return target if target.startswith(("http://", "https://")) else f"http://{target}"


def _title(body):
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    return m.group(1).strip() if m else ""


def _meta_generator(body):
    patterns = (
        r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']generator["\']',
    )
    for pattern in patterns:
        m = re.search(pattern, body, re.I | re.S)
        if m:
            return m.group(1).strip()
    return ""


def _echo(args):
    return {"value": args.get("msg", "")}


def _fingerprint_cve(args):
    fingerprints = args.get("fingerprints") or []
    matches = []
    for fingerprint in fingerprints:
        text = str(fingerprint).strip().lower()
        if not text:
            continue
        version_match = re.search(r"\d+(?:\.\d+)+", text)
        version = version_match.group(0) if version_match else text
        for pattern, name, cves in _CVE_RULES:
            if pattern.search(text):
                matches.append({"name": name, "version": version, "cves": list(cves)})
    return {"matches": matches, "count": len(matches)}


def _b64url_decode(segment: str) -> str:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", "replace")


def _jwt_analyze(args):
    token = str(args.get("jwt") or "")
    if not token:
        return {"error": "jwt is required", "header": {}, "payload": {}, "vulnerabilities": []}
    parts = token.split(".")
    if len(parts) < 2:
        return {"error": "invalid jwt: expected header.payload[.signature]", "header": {}, "payload": {}, "vulnerabilities": []}
    try:
        header = json.loads(_b64url_decode(parts[0]))
    except Exception:
        header = {}
    try:
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception:
        payload = {}
    if not isinstance(header, dict):
        header = {}
    if not isinstance(payload, dict):
        payload = {}

    vulnerabilities = []
    alg = str(header.get("alg") or "")
    if alg.lower() in ("none", "null"):
        vulnerabilities.append({
            "type": "alg_none",
            "severity": "high",
            "detail": "算法为 none/null，可绕过签名伪造任意 token",
        })
    kid = str(header.get("kid") or "")
    if re.search(r"[/\\]|\.\.|[\s]", kid):
        vulnerabilities.append({
            "type": "kid_injection",
            "severity": "high",
            "detail": f"kid 含路径/空白字符，可能存在路径注入：{kid!r}",
        })
    header_json = json.dumps(header, ensure_ascii=False)
    jwk = header.get("jwk") if isinstance(header.get("jwk"), dict) else {}
    if alg == "HS256" and (jwk.get("kty") == "RSA" or "RS256" in header_json):
        vulnerabilities.append({
            "type": "rs_to_hs",
            "severity": "high",
            "detail": "RS256 token 被降级为 HS256，可使用公钥作为 HMAC 密钥伪造",
        })
    return {"header": header, "payload": payload, "algorithm": alg, "vulnerabilities": vulnerabilities}


_JS_CALL_RE = re.compile(
    r"""(?:axios\.(?P<method>get|post|put|delete|patch)\(\s*["'](?P<url>[^"']+)["']|fetch\(\s*["'](?P<furl>[^"']+)["']\s*(?:,\s*\{[^}]*?method\s*:\s*["'](?P<fmethod>get|post|put|delete|patch)["'])?|request\(\s*\{[^}]*?url\s*:\s*["'](?P<rurl>[^"']+)["'][^}]*?(?:method\s*:\s*["'](?P<rmethod>get|post|put|delete|patch)["'])?)""",
    re.I,
)

_JS_SECRET_RE = re.compile(
    r"\b(?:api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|password|passwd)\b\s*[:=]\s*[\"']([^\"']+)[\"']",
    re.I,
)


def _object_params(text: str) -> list[str]:
    params = []
    for obj in re.finditer(r"\{([^{}]*)\}", text):
        names = re.findall(r"\b([A-Za-z_$][\w$]*)\s*:", obj.group(1))
        names += re.findall(r"([A-Za-z_$][\w$]*)(?=\s*(?:,|}|$))", obj.group(1))
        for name in names:
            if name not in params:
                params.append(name)
    return params


def _query_params(url: str) -> list[str]:
    return [k for k, _ in urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)]


def _call_window(js: str, start: int) -> str:
    open_idx = js.find("(", start)
    if open_idx == -1:
        return ""
    depth = 0
    for i in range(open_idx, len(js)):
        if js[i] == "(":
            depth += 1
        elif js[i] == ")":
            depth -= 1
            if depth == 0:
                return js[start:i]
    return ""


def _extract_js_secrets(text: str) -> list[str]:
    secrets = []
    for match in _JS_SECRET_RE.finditer(text):
        value = match.group(1).strip()
        if len(value) >= 6 and value not in secrets:
            secrets.append(value)
    return secrets


def _fetch_js_bundle(target: str) -> str:
    parts = []
    try:
        final, _, _, body = _fetch(_url_for(target))
        base = urllib.parse.urljoin(final, "/")
        for raw in re.findall(r"""<script[^>]+src=["']([^"']+)["']""", body, re.I):
            src = urllib.parse.urljoin(base, raw)
            if not src.startswith(("http://", "https://")):
                continue
            try:
                _, _, _, script = _fetch(src)
                parts.append(script)
            except Exception:
                continue
            if len(parts) >= 5:
                break
    except Exception:
        pass
    return "\n".join(parts)


def _js_extract(args):
    js = args.get("js")
    if js is None:
        target = args.get("target", "")
        if not target:
            return {"error": "js or target is required", "endpoints": [], "secrets": []}
        js = _fetch_js_bundle(target)
    elif isinstance(js, list):
        parts = []
        for item in js[:5]:
            text = str(item)
            if text.startswith(("http://", "https://")):
                try:
                    _, _, _, body = _fetch(text)
                    parts.append(body)
                except Exception:
                    continue
            else:
                parts.append(text)
        js = "\n".join(parts)
    else:
        text = str(js)
        if text.startswith(("http://", "https://")):
            try:
                _, _, _, js = _fetch(text)
            except Exception:
                js = ""
    js = js or ""

    endpoints = []
    seen = set()
    for match in _JS_CALL_RE.finditer(js):
        raw_url = match.group("url") or match.group("furl") or match.group("rurl")
        if not raw_url:
            continue
        method = (match.group("method") or match.group("fmethod") or match.group("rmethod") or "GET").upper()
        parsed = urllib.parse.urlsplit(raw_url)
        if parsed.scheme:
            url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        else:
            url = parsed.path
        window = _call_window(js, match.start())
        params = list(dict.fromkeys(_object_params(window) + _query_params(raw_url)))
        key = (url, method)
        if key not in seen:
            seen.add(key)
            endpoints.append({"url": url, "method": method, "params": params})
    return {"endpoints": endpoints, "secrets": _extract_js_secrets(js), "count": len(endpoints)}


def _value_fuzz(args):
    endpoints = args.get("endpoints") or []
    pool = []
    for entry in args.get("pool") or []:
        if isinstance(entry, dict) and entry.get("key") is not None:
            pool.append({"key": str(entry["key"]), "value": entry.get("value")})
    probes = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        url = str(endpoint.get("url") or "")
        method = str(endpoint.get("method") or "GET").upper() or "GET"
        params = [str(p) for p in (endpoint.get("params") or [])]
        for entry in pool:
            key = entry["key"]
            if key in params or "{" + key + "}" in url or ":" + key in url:
                probes.append({
                    "endpoint": url,
                    "param": key,
                    "value": entry["value"],
                    "method": method,
                })
    return {"probes": probes, "count": len(probes)}


_CRYPTO_KEY_RE = re.compile(
    r"\b(?:(?P<algo>aes|des|rsa|hmac|ec)(?:[_-]?key)?|private[_-]?key|secret|api[_-]?key)\b\s*[:=]\s*[\"']([^\"']+)[\"']",
    re.I,
)


def _crypto_analyze(args):
    text = str(args.get("text") or "")
    keys = []
    for match in _CRYPTO_KEY_RE.finditer(text):
        algo = (match.group("algo") or "").upper()
        matched = match.group(0).lower()
        if not algo:
            algo = "RSA" if "private" in matched else "SECRET"
        key = match.group(2).strip()
        if key:
            keys.append({"type": algo, "key": key})

    weak = []
    for entry in keys:
        length = len(entry["key"])
        if entry["type"] == "DES" and length < 8:
            weak.append({"type": "DES", "detail": "DES key too short (need 8 bytes)"})
        elif entry["type"] == "AES" and length not in (16, 24, 32):
            weak.append({"type": "AES", "detail": "AES key length invalid (need 16/24/32 bytes)"})
        elif entry["type"] == "RSA" and length < 64:
            weak.append({"type": "RSA", "detail": "RSA private key suspiciously short"})
    return {"keys": keys, "weak": weak, "weak_count": len(weak)}


_VULN_PROBE_PATHS = [
    "/.env", "/actuator/env", "/actuator/health", "/WEB-INF/web.xml",
    "/phpinfo.php", "/swagger-ui.html", "/v2/api-docs", "/.git/config",
]


def _sim_facts(items: list[dict], summary: str, extra: dict | None = None) -> dict:
    """items[]/stats/summary shaped exactly like the real-tool parsers' facts
    contract (parsers/__init__.py), so args_from / asset_extractor / gates see
    the same structure in both tiers."""
    stats = {"total": len(items)}
    for item in items:
        kind = item.get("type", "unknown")
        stats[kind] = stats.get(kind, 0) + 1
    if extra:
        stats.update(extra)
    return {"summary": summary[:300], "items": items, "stats": stats}


def _sim_facts_into(result: dict, items: list[dict], summary: str, extra: dict | None = None) -> dict:
    result.update(_sim_facts(items, summary, extra))
    return result


def _sim_finding(value: str, severity: str, template_id: str = "", msg: str = "") -> dict:
    return {"type": "finding", "value": value, "template_id": template_id,
            "name": msg or template_id, "severity": severity, "cve": []}


def _nuclei(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    url = _url_for(target).rstrip("/")
    findings = []
    for path in _VULN_PROBE_PATHS:
        try:
            _, status, _, _ = _fetch(url + path, timeout=6)
        except urllib.error.HTTPError as exc:
            status = exc.code
        except Exception:
            continue
        if 200 <= status < 400:
            findings.append({"template": "exposed-path", "path": path, "status": status, "severity": "info"})
    result = {"target": url, "findings": findings, "count": len(findings)}
    items = [
        _sim_finding(url + f["path"], f["severity"], template_id=f["template"], msg="exposed path")
        for f in findings
    ]
    return _sim_facts_into(result, items, f"{len(items)} 条漏洞发现" if items else "0 条漏洞发现")


def _sqlmap(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    if "?" not in target:
        return {"target": target, "findings": [], "count": 0, "note": "no query parameter to test"}
    body = ""
    try:
        _, status, _, body = _fetch(target + "'", timeout=6)
    except Exception:
        body = ""
    markers = ("sql syntax", "mysql", "postgres", "sqlite", "unclosed quotation", "microsoft ole db", "oracle")
    findings = []
    if any(m in body.lower() for m in markers):
        findings.append({"type": "error-based-sqli", "target": target, "severity": "high"})
    result = {"target": target, "findings": findings, "count": len(findings)}
    items = [_sim_finding(f["target"], f["severity"], msg=f["type"]) for f in findings]
    return _sim_facts_into(result, items, f"{len(items)} 条 SQL 注入疑似")


def _dalfox(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    marker = "xssprobe_lattice"
    body = ""
    if "?" in target:
        probe_url = target + ("&" if "&" in target else "?") + f"q={marker}"
        try:
            _, status, _, body = _fetch(probe_url, timeout=6)
        except Exception:
            body = ""
    findings = []
    if marker in body:
        findings.append({"type": "reflected-xss", "target": target, "severity": "medium"})
    result = {"target": target, "findings": findings, "count": len(findings)}
    items = [_sim_finding(f["target"], f["severity"], msg=f["type"]) for f in findings]
    return _sim_facts_into(result, items, f"{len(items)} 条 XSS 发现")


def _dnsx(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    try:
        infos = socket.getaddrinfo(target, None)
    except socket.gaierror as exc:
        return {"error": f"resolution failed: {exc}"}
    seen = []
    for family, _, _, _, sockaddr in infos:
        addr = sockaddr[0]
        if addr not in seen:
            seen.append(addr)
    result = {"target": target, "addresses": seen, "records": len(seen)}
    items = [{"type": "domain", "value": target, "a_record": seen}] if seen else []
    return _sim_facts_into(result, items, f"{len(items)} 条 DNS A 记录")


def _httpx(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    url = _url_for(target)
    try:
        final, status, headers, body = _fetch(url)
        result = {"url": final, "status": status, "server": headers.get("server", ""),
                  "title": _title(body)}
        items = [{"type": "url", "value": final, "status_code": status, "title": result["title"],
                  "tech": [result["server"]] if result["server"] else [], "cdn": False,
                  "host": urllib.parse.urlparse(final).hostname or ""}]
        return _sim_facts_into(result, items, f"{len(items)} 个存活 Web 端点")
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": exc.code, "error": f"http {exc.code}"}
    except Exception as exc:
        return {"error": f"probe failed: {exc}"}


def _whatweb(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    url = _url_for(target)
    try:
        final, status, headers, body = _fetch(url)
        tech = []
        server = headers.get("server", "")
        if server and server.lower() != "none":
            tech.append(f"server={server}")
        powered = headers.get("x-powered-by", "")
        if powered:
            tech.append(f"powered-by={powered}")
        generator = _meta_generator(body)
        if generator:
            tech.append(f"generator={generator}")
        lowered = body.lower()
        for name, markers in _CMS_MARKERS:
            if any(marker in lowered for marker in markers) and name not in tech:
                tech.append(name)
        return {"url": final, "status": status, "server": server, "technologies": tech}
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": exc.code, "error": f"http {exc.code}"}
    except Exception as exc:
        return {"error": f"probe failed: {exc}"}


def _crt_sh(target):
    query = urllib.parse.quote(target)
    url = f"https://crt.sh/?q=%25.{query}&output=json"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    names = set()
    for row in data:
        for n in row.get("name_value", "").split("\n"):
            n = n.strip().lower()
            if n and n.endswith(target):
                names.add(n)
    return names


def _hackertarget(target):
    url = f"https://api.hackertarget.com/hostsearch/?q={urllib.parse.quote(target)}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        text = resp.read().decode("utf-8", "replace")
    names = set()
    for line in text.splitlines():
        host = line.split(",", 1)[0].strip().lower()
        if host.endswith(target) and host != target:
            names.add(host)
    return names


def _dns_brute(target):
    def resolve(sub):
        host = f"{sub}.{target}"
        try:
            socket.getaddrinfo(host, None)
            return host
        except OSError:
            return None

    names = set()
    if not _COMMON_SUBDOMAINS:
        return names
    with ThreadPoolExecutor(max_workers=min(12, len(_COMMON_SUBDOMAINS))) as ex:
        for host in ex.map(resolve, _COMMON_SUBDOMAINS):
            if host:
                names.add(host)
    return names


def _subfinder(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    errors = []
    names = set()
    source = ""
    for label, fetcher in (("crt.sh", _crt_sh), ("hackertarget", _hackertarget)):
        try:
            found = fetcher(target)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue
        if found:
            names.update(found)
            source = label
            break
    if not names:
        try:
            found = _dns_brute(target)
            if found:
                names.update(found)
                source = "dns-brute"
        except Exception as exc:
            errors.append(f"dns-brute: {exc}")
    result = {
        "target": target,
        "subdomains": sorted(names),
        "count": len(names),
        "source": source,
        "incomplete": bool(errors),
    }
    if errors:
        result["error"] = "; ".join(errors)
    items = [{"type": "domain", "value": h, "source": source or "sim"} for h in sorted(names)]
    return _sim_facts_into(result, items, f"{len(items)} 个子域")


_COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 993, 995,
                 1433, 3306, 3389, 5432, 5900, 6379, 8080, 8443, 9200, 27017]


def _naabu_scan(target, ports):
    valid = []
    for port in ports:
        try:
            valid.append(int(port))
        except (TypeError, ValueError):
            continue

    def probe(port):
        try:
            with socket.create_connection((target, port), timeout=1.5):
                return port
        except OSError:
            return None

    if not valid:
        return []
    with ThreadPoolExecutor(max_workers=min(12, len(valid))) as ex:
        results = list(ex.map(probe, valid))
    return [p for p in results if p is not None]


def _naabu(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    ports = args.get("ports") or _COMMON_PORTS
    open_ports = _naabu_scan(target, ports)
    result = {"target": target, "open_ports": open_ports}
    items = [{"type": "port", "value": f"{target}:{p}", "host": target, "port": p} for p in open_ports]
    return _sim_facts_into(result, items, f"{len(items)} 个开放端口")


def _nmap(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    ports = args.get("ports") or _COMMON_PORTS
    open_ports = _naabu_scan(target, ports)
    result = {"target": target, "open_ports": open_ports, "mode": "conservative"}
    items = [{"type": "port", "value": f"{target}:{p}", "host": target, "port": p} for p in open_ports]
    return _sim_facts_into(result, items, f"{len(items)} 个开放端口")


_COMMON_PATHS = ["/", "/admin", "/api", "/robots.txt", "/sitemap.xml", "/.env",
                 "/.git/HEAD", "/.git/config", "/backup", "/config", "/.htaccess",
                 "/server-status", "/wp-admin", "/wp-login.php", "/.DS_Store",
                 "/swagger", "/v2/api-docs", "/phpinfo.php", "/.well-known/security.txt"]


def _ffuf(args):
    raw = args.get("target", "")
    if not raw:
        return {"error": "target is required"}
    target = _url_for(raw).rstrip("/")
    found = []
    blocked = []
    for path in _COMMON_PATHS:
        try:
            _, status, _, _ = _fetch(target + path, timeout=6)
            found.append({"path": path, "status": status})
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in (401, 403, 405):
                found.append({"path": path, "status": status})
            elif status == 429 or status >= 500:
                blocked.append({"path": path, "status": status})
        except Exception:
            continue
    result = {"target": target, "paths": found, "blocked": blocked, "blocked_count": len(blocked)}
    items = [{"type": "url", "value": target + f["path"], "status": f["status"],
              "input": f["path"].strip("/")} for f in found]
    return _sim_facts_into(result, items, f"{len(items)} 个 fuzz 命中")


_ATTR_RE = re.compile(r"""(?:href|src)=["']([^"']+)["']""", re.I)


def _katana(args):
    target = args.get("target", "")
    if not target:
        return {"error": "target is required"}
    url = _url_for(target)
    try:
        final, _, _, body = _fetch(url)
        base = urllib.parse.urljoin(final, "/")
        links = []
        for raw in _ATTR_RE.findall(body):
            resolved = urllib.parse.urljoin(base, raw)
            if resolved not in links:
                links.append(resolved)
        result = {"url": final, "links": links}
        items = [{"type": "url", "value": link, "method": "GET", "source": "sim", "tag": ""} for link in links]
        return _sim_facts_into(result, items, f"{len(items)} 个爬取到的 URL")
    except Exception as exc:
        return {"error": f"crawl failed: {exc}"}


@register_tool("record_finding", "Record a structured finding for the current run", category="evidence")
def record_finding(args):
    title = str(args.get("title") or "").strip()
    if not title:
        return {"error": "finding title is required", "recorded": False}
    finding = {
        "title": title,
        "severity": str(args.get("severity") or "medium"),
        "status": str(args.get("status") or "pending"),
        "target": str(args.get("target") or ""),
        "cwe": str(args.get("cwe") or ""),
        "confidence": str(args.get("confidence") or "unverified"),
        "evidence_ids": list(args.get("evidence_ids") or []),
        "summary": str(args.get("summary") or ""),
        "impact": str(args.get("impact") or ""),
        "remediation": str(args.get("remediation") or ""),
    }
    return {"recorded": True, "finding": finding}


@register_tool("record_loot", "Record looted data (files, credentials, tokens) for the current run", category="evidence")
def record_loot(args):
    data = args.get("data")
    if not isinstance(data, dict) or not data:
        return {"error": "loot data is required", "recorded": False}
    return {"recorded": True, "loot": data}


@register_tool("record_host", "Record a discovered host/asset for the current run", category="evidence")
def record_host(args):
    host = str(args.get("host") or "").strip()
    if not host:
        return {"error": "host is required", "recorded": False}
    return {
        "recorded": True,
        "asset": {
            "kind": str(args.get("kind") or "host"),
            "value": host,
            "note": str(args.get("note") or ""),
        },
    }


def install_builtins(registry: ToolRegistry) -> ToolRegistry:
    registry.register_builtin("echo", "return the msg argument", {}, {}, _echo)
    registry.register_builtin(
        "dnsx", "内置轻量近似：DNS 记录解析（不等于真实 dnsx）",
        {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
        {}, _dnsx, category="recon")
    registry.register_builtin(
        "httpx", "内置轻量近似：HTTP 存活探测",
        {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
        {}, _httpx, category="recon")
    registry.register_builtin(
        "whatweb", "内置轻量近似：响应头/页面技术特征识别",
        {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
        {}, _whatweb, category="recon")
    registry.register_builtin(
        "subfinder", "内置轻量近似：crt.sh 被动子域枚举",
        {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
        {}, _subfinder, category="recon")
    registry.register_builtin(
        "naabu", "内置轻量近似：常见端口 TCP 探测",
        {"type": "object", "properties": {"target": {"type": "string"}}}, {}, _naabu, category="recon")
    registry.register_builtin(
        "nmap", "内置轻量近似：常见端口扫描（不等于真实 nmap）",
        {"type": "object", "properties": {"target": {"type": "string"}}}, {}, _nmap, category="recon")
    registry.register_builtin(
        "ffuf", "内置轻量近似：固定路径探测（不等于真实 ffuf）",
        {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
        {}, _ffuf, category="recon")
    registry.register_builtin(
        "katana", "内置轻量近似：抓取首页链接",
        {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
        {}, _katana, category="recon")
    registry.register_builtin(
        "fingerprint_cve", "依赖版本→CVE 匹配（Log4j/Shiro/Fastjson/Spring Boot/Struts2）",
        {"type": "object", "properties": {"fingerprints": {"type": "array", "items": {"type": "string"}}}},
        {}, _fingerprint_cve, category="analysis")
    registry.register_builtin(
        "jwt_analyze", "JWT 攻击检测（alg none/kid 注入/RS→HS 降级）",
        {"type": "object", "properties": {"jwt": {"type": "string"}}},
        {}, _jwt_analyze, category="analysis")
    registry.register_builtin(
        "js_extract", "JS 端点/参数提取（axios/fetch/request）",
        {"type": "object", "properties": {"js": {"type": "string"}, "target": {"type": "string"}}},
        {}, _js_extract, category="analysis")
    registry.register_builtin(
        "value_fuzz", "值池联动 fuzz（把接口返回的 token/id 喂给其他端点）",
        {"type": "object", "properties": {"endpoints": {"type": "array"}, "pool": {"type": "array"}}},
        {}, _value_fuzz, category="analysis")
    registry.register_builtin(
        "crypto_analyze", "加密弱项/密钥提取（AES/DES/RSA/硬编码 secret）",
        {"type": "object", "properties": {"text": {"type": "string"}}},
        {}, _crypto_analyze, category="analysis")
    registry.register_builtin(
        "nuclei", "内置轻量近似：敏感路径探测（真实 nuclei 缺失时回退）",
        {"type": "object", "properties": {"target": {"type": "string"}}},
        {}, _nuclei, category="vuln")
    registry.register_builtin(
        "sqlmap", "内置轻量近似：SQL 错误探测（真实 sqlmap 缺失时回退）",
        {"type": "object", "properties": {"target": {"type": "string"}}},
        {}, _sqlmap, category="vuln")
    registry.register_builtin(
        "dalfox", "内置轻量近似：反射型 XSS 探测（真实 dalfox 缺失时回退）",
        {"type": "object", "properties": {"target": {"type": "string"}}},
        {}, _dalfox, category="vuln")
    for name, spec in _BUILTIN_SPECS.items():
        registry.register_builtin_tool(spec["tool"], spec["func"])
    # Real-tool registry entries register as runner="cli" and shadow the
    # same-name sim; the missing-executable fallback keeps them resilient.
    from lattice_ai.toolchain_registry import install_registry_tools
    install_registry_tools(registry)
    return registry
