import json
import sys


def _reply(request, result):
    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}))
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            continue
        method = request.get("method")
        if method == "initialize":
            _reply(request, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lattice-sample-mcp", "version": "0.1.0"},
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _reply(request, {
                "tools": [
                    {
                        "name": "scan_port",
                        "description": "Check whether a target host has an open port",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "port": {"type": "integer", "default": 80},
                            },
                            "required": ["target"],
                        },
                    }
                ]
            })
        elif method == "tools/call":
            name = request.get("params", {}).get("name")
            args = request.get("params", {}).get("arguments", {})
            if name == "scan_port":
                _reply(request, {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"target": args.get("target"), "port": args.get("port", 80), "open": False}),
                    }]
                })
            else:
                _reply(request, {"error": {"code": -32602, "message": "unknown tool"}})


if __name__ == "__main__":
    main()
