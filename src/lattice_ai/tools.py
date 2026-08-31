import copy
import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
import time

import jsonschema

from lattice_ai.models import Tool
from lattice_ai import parsers
from lattice_ai.danger import DangerVerdict, evaluate_danger
from lattice_ai.scope import evaluate_scope, scope_policy_from_dict


_BUILTIN_SPECS: dict[str, dict] = {}
_PORT_SCOPE_TOOLS = {"nmap", "naabu"}


def register_tool(name: str, description: str = "", parameters: dict | None = None,
                  output: dict | None = None, category: str = "general", enabled: bool = True):
    """Decorator that registers a builtin tool implementation with metadata.

    ``install_builtins`` picks these up for every new ``ToolRegistry``.
    """

    def decorator(func):
        _BUILTIN_SPECS[name] = {
            "tool": Tool(
                name=name,
                description=description,
                parameters=parameters or {},
                output=output or {},
                runner="builtin",
                category=category,
                enabled=enabled,
            ),
            "func": func,
        }
        return func

    return decorator


class ToolError(Exception):
    pass


class ApprovalDenied(ToolError):
    pass


class ScopeViolation(ToolError):
    pass


class DangerDenied(ToolError):
    def __init__(self, verdict: DangerVerdict):
        super().__init__(f"danger action {verdict.action}: {verdict.reason}")
        self.verdict = verdict


class Adapter:
    """A Tool runtime adapter. invoke() executes an adapted tool and returns a dict."""

    def __init__(self, name: str):
        self.name = name

    def invoke(self, tool: Tool, args: dict, *, timeout: float = 60.0, cwd=None) -> dict:
        raise NotImplementedError


_ADAPTERS: dict[str, Adapter] = {}


def register_adapter(adapter: Adapter) -> Adapter:
    _ADAPTERS[adapter.name] = adapter
    return adapter


def get_adapter(name: str) -> Adapter | None:
    return _ADAPTERS.get(name)


_EXTRA_TOOL_PATHS: list[str] = []


def add_tool_path(path: str) -> None:
    if path and path not in _EXTRA_TOOL_PATHS:
        _EXTRA_TOOL_PATHS.append(path)


def find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    extensions = [".exe", ".bat", ".cmd", ""] if os.name == "nt" else [""]
    for directory in _EXTRA_TOOL_PATHS:
        for extension in extensions:
            candidate = os.path.join(directory, name + extension)
            if os.path.isfile(candidate):
                return candidate
    return None


# A binary on PATH that merely shares the tool's name is not necessarily the
# real tool (unrelated `httpx`/`nmap` clones exist in the wild). Registry
# entries carry version_cmd+version_regex, so a candidate executable must
# identify itself before we trust it; otherwise treat as missing (-> sim
# fallback). Results are cached per executable path.
_IDENTITY_TTL = 30.0
_identity_cache: dict[str, tuple[float, bool]] = {}
_identity_lock = threading.Lock()


def _registry_identity_ok(tool_name: str, executable: str) -> bool:
    from lattice_ai import toolchain_registry as tcr

    entry = tcr.get_entry(tool_name)
    if entry is None or not entry.version_cmd or not entry.version_regex:
        return True
    if entry.av_sensitive:
        # probing would trigger the user's antivirus; trust the file name
        return True
    now = time.monotonic()
    with _identity_lock:
        cached = _identity_cache.get(executable)
        if cached and now - cached[0] < _IDENTITY_TTL:
            return cached[1]
    ok = False
    try:
        argv = [executable, *entry.version_cmd[1:]]
        if executable.lower().endswith((".bat", ".cmd")):
            argv = ["cmd", "/c", *argv]
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,  # some tools (sqlmap) prompt interactively
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        ok = re.search(entry.version_regex, output) is not None
    except Exception:
        ok = False
    with _identity_lock:
        _identity_cache[executable] = (time.monotonic(), ok)
    return ok


def find_real_executable(name: str) -> str | None:
    """find_executable + registry identity verification in one step."""
    exe = find_executable(name)
    if exe is None:
        return None
    return exe if _registry_identity_ok(name, exe) else None


def tool_available(tool: Tool) -> bool:
    if tool.runner == "builtin":
        return True
    if tool.runner == "adapter":
        return get_adapter(tool.adapter) is not None
    if tool.runner == "cli":
        if not tool.command:
            return False
        return find_executable(tool.command[0]) is not None
    return False


def tool_status(tool: Tool) -> str:
    if tool.runner == "builtin":
        return "builtin"
    if tool.runner == "adapter":
        return "adapter" if get_adapter(tool.adapter) else "unavailable"
    if tool.runner == "cli":
        return "cli" if (tool.command and find_executable(tool.command[0])) else "unavailable"
    return "unavailable"


def validate_arguments(tool: Tool, args: dict) -> dict:
    if tool.parameters:
        jsonschema.validate(instance=args, schema=tool.parameters)
    return args


def validate_output(tool: Tool, result: dict) -> dict:
    if tool.output:
        jsonschema.validate(instance=result, schema=tool.output)
    return result


def _validate_secret_fields(tool: Tool) -> None:
    if not tool.secret_fields or not tool.output:
        return
    props = tool.output.get("properties", {})
    for path in tool.secret_fields:
        top = path.split(".")[0]
        if top not in props:
            raise ToolError(f"secret_field {path!r} does not match output schema")


def _set_path(data: dict, path: str, value) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict):
        node[parts[-1]] = value


def redact(result: dict, secret_fields: list[str]) -> dict:
    redacted = copy.deepcopy(result)
    for path in secret_fields:
        _set_path(redacted, path, "[REDACTED]")
    return redacted


def _truncate(text: str, limit: int = 20000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _normalize_cli_output(tool: Tool, proc) -> dict:
    """Parse on the FULL output first; truncation only applies to the stored
    raw/stdout copies (large JSONL output used to be cut before parsing)."""
    stdout_full = proc.stdout or ""
    stderr_full = proc.stderr or ""
    parsed = parsers.parse(tool, stdout_full, stderr_full, proc.returncode)
    if parsed is not None:
        parsed["raw"] = _truncate(parsed.get("raw", stdout_full))
        parsed["stdout"] = _truncate(stdout_full)
        parsed["stderr"] = _truncate(stderr_full)
        parsed["returncode"] = proc.returncode
        return parsed
    result = {"stdout": _truncate(stdout_full), "stderr": _truncate(stderr_full), "returncode": proc.returncode}
    try:
        data = json.loads(stdout_full)
    except Exception:
        data = None
    if isinstance(data, dict):
        return {**data, **result}
    return result


def _with_tier(result: dict, tier: str, reason: str) -> dict:
    """Attach the explicit tier signal consumed by executor/agents (T-T3)."""
    if isinstance(result, dict):
        result["_tool_tier"] = {"tier": tier, "reason": reason}
    return result


def _emit_tier(event_log, name: str, tier: str, reason: str) -> None:
    if event_log is not None:
        event_log.append("tool_tier", {"tool": name, "tier": tier, "reason": reason})


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._builtins = {}
        self.default_scope_policy = None
        self.default_danger_policy = None
        self.default_run_allowances = set()

    def set_security_context(self, *, scope_policy=None, danger_policy=None, run_allowances=None):
        self.default_scope_policy = scope_policy
        self.default_danger_policy = danger_policy
        self.default_run_allowances = set(run_allowances or [])

    def register(self, tool: Tool) -> None:
        if tool.runner == "builtin":
            if tool.name not in self._builtins:
                raise ToolError(
                    f"builtin tool {tool.name!r} has no function; call register_builtin first"
                )
            # Keep the registered builtin schema (params/output); do not let a
            # template's builtin binding overwrite it.
            return
        if tool.runner == "adapter" and tool.adapter not in _ADAPTERS:
            raise ToolError(f"adapter {tool.adapter!r} is not registered")
        _validate_secret_fields(tool)
        self._tools[tool.name] = tool

    def register_builtin(self, name, description, parameters, output, func, *, category="general", enabled=True) -> None:
        self._builtins[name] = func
        self._tools[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            output=output,
            runner="builtin",
            category=category,
            enabled=enabled,
        )

    def register_builtin_tool(self, tool: Tool, func) -> None:
        self._builtins[tool.name] = func
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"unknown tool: {name}")
        return self._tools[name]

    def list_tools(self, category: str | None = None) -> list[Tool]:
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    def enable_tool(self, name: str) -> None:
        self.get(name).enabled = True

    def disable_tool(self, name: str) -> None:
        self.get(name).enabled = False

    def run(
        self,
        name: str,
        args: dict,
        *,
        timeout: float = 60.0,
        cwd=None,
        approver=None,
        scope_policy: dict | None = None,
        danger_policy: dict | None = None,
        run_allowances: set[str] | None = None,
        event_log=None,
    ):
        tool = self.get(name)
        if not tool.enabled:
            raise ToolError(f"tool {name!r} is disabled")
        try:
            validate_arguments(tool, args)
        except Exception as exc:
            raise ToolError(f"invalid arguments for {name}: {exc}") from exc

        self._check_approval(tool, args, approver)
        if tool.runner != "builtin":
            _enforce_scope(tool, args)

        effective_scope = scope_policy if scope_policy is not None else self.default_scope_policy
        effective_danger = danger_policy if danger_policy is not None else self.default_danger_policy
        effective_allowances = run_allowances if run_allowances is not None else self.default_run_allowances

        if effective_scope is not None:
            policy = scope_policy_from_dict(effective_scope)
            ok, reason = evaluate_scope(policy, str(args.get("target") or ""))
            if not ok:
                raise ScopeViolation(f"tool {name!r} is outside scope: {reason}")

        # allow_ports is an operational filter, not an authorization gate: when
        # the user configured which ports to probe, feed them to builtin port
        # scanners so they scan only that set (never overriding an explicit arg).
        if effective_scope is not None and name in _PORT_SCOPE_TOOLS:
            scope_policy = scope_policy_from_dict(effective_scope)
            if scope_policy.allow_ports and "ports" not in args:
                args = {**args, "ports": list(scope_policy.allow_ports)}

        if effective_danger is not None:
            verdict = evaluate_danger(effective_danger, tool, args, run_allowances=effective_allowances)
            if verdict.action != "allow":
                raise DangerDenied(verdict)

        if tool.runner == "builtin":
            func = self._builtins.get(name)
            if func is None:
                raise ToolError(f"builtin tool {name!r} has no function")
            result = func(args)
            result = result if isinstance(result, dict) else {"value": result}
        elif tool.runner == "adapter":
            adapter = get_adapter(tool.adapter)
            if adapter is None:
                raise ToolError(f"adapter {tool.adapter!r} not registered")
            result = adapter.invoke(tool, args, timeout=timeout, cwd=cwd)
            result = result if isinstance(result, dict) else {"value": result}
        else:
            executable = find_executable(tool.command[0]) if tool.command else None
            if executable is not None and not _registry_identity_ok(name, executable):
                # Name collision with an unrelated binary on PATH: treat as missing.
                executable = None
            fallback_func = None
            if tool.command and executable is None:
                fallback_func = self._builtins.get(name)
            if fallback_func is not None:
                result = fallback_func(args)
                result = result if isinstance(result, dict) else {"value": result}
                result = _with_tier({**result, "fallback": True}, "sim", "missing_fallback")
                _emit_tier(event_log, name, "sim", "missing_fallback")
                return result
            try:
                argv = [str(part).format(**args) for part in tool.command]
            except (KeyError, IndexError) as exc:
                raise ToolError(f"tool {name} missing required argument: {exc}") from exc
            if executable:
                argv = [executable, *argv[1:]]
                if executable.lower().endswith((".bat", ".cmd")):
                    argv = ["cmd", "/c", *argv]
            try:
                proc = subprocess.run(
                    argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=timeout, cwd=cwd,
                )
            except subprocess.TimeoutExpired as exc:
                return {"error": f"tool {name} timed out after {timeout}s"}
            except FileNotFoundError:
                fallback_func = self._builtins.get(name)
                if fallback_func is not None:
                    result = fallback_func(args)
                    result = result if isinstance(result, dict) else {"value": result}
                    result = _with_tier({**result, "fallback": True}, "sim", "missing_fallback")
                    _emit_tier(event_log, name, "sim", "missing_fallback")
                    return result
                return {"error": f"tool {name} executable not found: {argv[0]}"}
            result = _normalize_cli_output(tool, proc)
            result = _with_tier(result, "real", "installed")
            _emit_tier(event_log, name, "real", "installed")
            if event_log is not None and isinstance(result, dict) and result.get("parse_error"):
                event_log.append("parse_fallback", {"tool": name, "reason": result["parse_error"]})

        try:
            validate_output(tool, result)
        except Exception as exc:
            raise ToolError(f"invalid output for {name}: {exc}") from exc
        return result

    def run_sim(self, name: str, args: dict, *, event_log=None):
        """Execute the same-name builtin simulator directly (binding tier="sim")."""
        func = self._builtins.get(name)
        if func is None:
            raise ToolError(f"tool {name!r} has no builtin simulator")
        result = func(args)
        result = result if isinstance(result, dict) else {"value": result}
        result = _with_tier(result, "sim", "forced_by_binding")
        _emit_tier(event_log, name, "sim", "forced_by_binding")
        return result

    def _check_approval(self, tool: Tool, args: dict, approver) -> None:
        if tool.approval == "deny":
            raise ApprovalDenied(f"tool {tool.name!r} is denied by policy")
        if tool.approval == "ask":
            if approver is None:
                raise ApprovalDenied(f"tool {tool.name!r} requires approval but no approver is configured")
            if not approver(tool, args):
                raise ApprovalDenied(f"tool {tool.name!r} was not approved")


def classify_target(target: str) -> str:
    value = (target or "").strip()
    if value.startswith(("http://", "https://")):
        return "web"
    if re.match(r"^[^/]+:\d+$", value):
        return "service"
    try:
        ipaddress.ip_interface(value)
        return "network"
    except ValueError:
        return "host"


def _enforce_scope(tool: Tool, args: dict) -> None:
    if not tool.scope:
        return
    target_type = classify_target(str(args.get("target") or ""))
    if target_type not in tool.scope:
        raise ToolError(f"tool {tool.name!r} target type '{target_type}' is outside scope {tool.scope}")
