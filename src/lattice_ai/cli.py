import argparse
import json
import os
import sys
from pathlib import Path

from lattice_ai.agent import StageAgent
from lattice_ai.builtins import install_builtins
from lattice_ai.events import EventLog
from lattice_ai.executor import Executor
from lattice_ai.llm import OpenAICompatibleProvider
from lattice_ai.persistence import load_template
from lattice_ai.tools import ToolRegistry


def _interactive_approver(tool, args):
    prompt = f"Approve tool {tool.name!r} with args {args}? [y/N] "
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")


def _serve_main(argv):
    parser = argparse.ArgumentParser(prog="lattice-ai serve", description="start the local Lattice AI service (API + web UI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8742)
    parser.add_argument("--no-browser", action="store_true", help="only start the service, do not open the browser")
    args = parser.parse_args(argv)

    import threading
    import time
    import urllib.request
    import webbrowser

    import uvicorn
    from lattice_ai.server import app

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{args.port}/"
    deadline = time.time() + 20
    while time.time() < deadline:
        if not thread.is_alive():
            print("[lattice] server thread exited; startup failed", file=sys.stderr)
            return 1
        try:
            with urllib.request.urlopen(f"{url}health", timeout=0.5) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass
        time.sleep(0.25)
    else:
        print("[lattice] timed out waiting for the service", file=sys.stderr)
        return 1

    print(f"[lattice] Lattice AI ready at {url}")
    print("[lattice] press Ctrl+C to stop")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    thread.join(timeout=5)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        return _serve_main(argv[1:])

    parser = argparse.ArgumentParser(
        prog="lattice-ai",
        description="run a Lattice AI template",
        epilog="subcommands: lattice-ai serve [--host H] [--port P] [--no-browser] — start the local web service",
    )
    parser.add_argument("template", help="path to template JSON")
    parser.add_argument("target", help="target IP/domain")
    parser.add_argument("--out", default="session.jsonl", help="session event log path")
    parser.add_argument("--cwd", default=None, help="working directory for CLI tools")
    parser.add_argument("--autonomous", action="store_true", help="run stages via the LLM agent")
    parser.add_argument("--base-url", default=os.environ.get("LATTICE_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--model", default=os.environ.get("LATTICE_MODEL", "gpt-5.1"))
    parser.add_argument("--api-key", default=os.environ.get("LATTICE_API_KEY", ""))
    parser.add_argument("--max-agent-iterations", type=int, default=10)
    args = parser.parse_args(argv)

    template = load_template(args.template)
    registry = ToolRegistry()
    install_builtins(registry)
    for tool in template.tools:
        registry.register(tool)

    log = EventLog(Path(args.out))
    agent = None
    if args.autonomous:
        if not args.api_key:
            parser.error("--autonomous requires --api-key or LATTICE_API_KEY")
        provider = OpenAICompatibleProvider(args.base_url, args.api_key, args.model)
        agent = StageAgent(provider, registry, log, approver=_interactive_approver, max_iterations=args.max_agent_iterations)

    facts = Executor(template, registry, log).run(
        args.target, cwd=args.cwd, approver=_interactive_approver, agent=agent
    ).facts
    log.flush()
    print(json.dumps(facts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
