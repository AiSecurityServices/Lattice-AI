import json
import subprocess

from lattice_ai.models import Tool
from lattice_ai.tools import Adapter


def _send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _recv(proc, want_id):
    for _ in range(120):
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("id") == want_id:
            return msg
    return None


class McpAdapter(Adapter):
    def __init__(self):
        super().__init__("mcp")

    def invoke(self, tool: Tool, args: dict, *, timeout: float = 60.0, cwd=None) -> dict:
        argv = [str(part).format(**args) for part in tool.command]
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
        )
        try:
            _send(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "lattice", "version": "0.1.0"},
                },
            })
            _recv(proc, 1)
            _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            _send(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool.ref, "arguments": args},
            })
            result = _recv(proc, 2)
            if not result or "error" in result:
                raise ValueError(f"mcp tool {tool.ref} failed: {result}")
            content = result.get("result", {}).get("content", [])
            text = "\n".join(c.get("text", "") for c in content)
            return {"text": text, "raw": result.get("result", {})}
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
