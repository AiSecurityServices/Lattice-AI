import json
import re
import urllib.parse
import urllib.request

from lattice_ai.models import Tool
from lattice_ai.tools import Adapter


class HttpApiAdapter(Adapter):
    def __init__(self):
        super().__init__("http_api")

    def invoke(self, tool: Tool, args: dict, *, timeout: float = 60.0, cwd=None) -> dict:
        method = tool.command[0].upper() if tool.command else "GET"
        base = tool.command[1] if len(tool.command) > 1 else ""
        path = tool.ref or ""
        full = base.rstrip("/") + "/" + path.lstrip("/")
        used = set(re.findall(r"\{([^}]+)\}", full))
        try:
            url = full.format(**args)
        except (KeyError, IndexError) as exc:
            raise ValueError(f"http_api tool {tool.name} missing arg: {exc}") from exc
        query = {k: v for k, v in args.items() if k not in used}
        if query:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
        data = None
        headers = {"User-Agent": "lattice-ai"}
        if method in ("POST", "PUT", "PATCH"):
            data = json.dumps({k: v for k, v in args.items()}).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"body": raw, "status": status}
