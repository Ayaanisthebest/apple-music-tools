"""Catalog features through the applemusic-mcp package, called from the command line.

Starts `applemusic-mcp serve --level api` (no browser player, no UI clicking),
makes one request and exits.
"""
import json
import shutil
import subprocess
import threading
from pathlib import Path

DESTRUCTIVE = ("delete", "remove", "logout", "reset", "clear")


def _binary():
    found = shutil.which("applemusic-mcp") or str(Path("~/.local/bin/applemusic-mcp").expanduser())
    if not Path(found).exists():
        raise RuntimeError("applemusic-mcp is not installed (pipx install applemusic-mcp==0.22.1)")
    return found


def _session(requests, timeout=600):
    proc = subprocess.Popen([_binary(), "serve", "--level", "api"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()

    def send(message):
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        proc.stdin.flush()

    def receive(number):
        for line in proc.stdout:
            reply = json.loads(line)
            if reply.get("id") == number and ("result" in reply or "error" in reply):
                if "error" in reply:
                    raise RuntimeError(reply["error"]["message"])
                return reply["result"]
        raise RuntimeError("applemusic-mcp stopped or timed out before answering")

    try:
        send({"id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "am", "version": "1"}}})
        receive(0)
        send({"method": "notifications/initialized"})

        def request(method, params):
            send({"id": 1 + request.count, "method": method, "params": params})
            request.count += 1
            return receive(request.count)
        request.count = 0
        return requests(request)
    finally:
        timer.cancel()
        proc.kill()
        proc.wait()


def _convert(text, schema):
    """Keep text where the tool accepts text; otherwise read it as JSON."""
    kinds = {s.get("type") for s in schema.get("anyOf", [schema])}
    if "string" in kinds:
        return text
    return json.loads(text)


def cloud(service=None, action=None, params=None, confirm=False):
    def run(request):
        tools = {t["name"]: t for t in request("tools/list", {})["tools"]}
        if not service:
            return {name: {"description": t["description"],
                           "params": sorted(t["inputSchema"].get("properties", {}))}
                    for name, t in tools.items()}
        if service not in tools:
            raise RuntimeError(f"Unknown cloud tool. Choose from: {', '.join(tools)}")
        if not action:
            return {service: tools[service]}
        # "replace" removes a track as part of an add.
        removes = action.lower().startswith(DESTRUCTIVE) or any(
            p.startswith("replace=") for p in params or [])
        if removes and not confirm:
            return {"preview": True, "wouldRun": {"service": service, "action": action, "params": params or []}}
        props = tools[service]["inputSchema"].get("properties", {})
        args = {"action": action}
        for pair in params or []:
            key, sep, value = pair.partition("=")
            if not sep or key not in props:
                raise RuntimeError(f"Expected key=value with a key from: {', '.join(sorted(props))}")
            args[key] = _convert(value, props[key])
        if confirm and "confirm" in props:
            args["confirm"] = True
        result = request("tools/call", {"name": service, "arguments": args})
        text = "\n".join(c.get("text", "") for c in result.get("content", []))
        if result.get("isError"):
            raise RuntimeError(text)
        return {"output": text}
    return _session(run)
