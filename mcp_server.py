#!/usr/bin/env python3
"""Minimal MCP server (stdio, no dependencies) exposing the Apple Music tools."""
import json
import sys

import core


def tool_list():
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props, "required": required,
                             "additionalProperties": False}}
            for name, (_, desc, props, required, _) in core.TOOLS.items()]


def handle(method, params):
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "apple-music", "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_list()}
    if method == "tools/call":
        try:
            result = core.call(params.get("name"), params.get("arguments") or {})
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
        except Exception as e:  # report tool failures to the client, keep serving
            return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
    raise LookupError(method)


for line in sys.stdin:
    if not line.strip():
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if "id" not in msg or "method" not in msg:
        continue  # notification or response
    reply = {"jsonrpc": "2.0", "id": msg["id"]}
    try:
        reply["result"] = handle(msg["method"], msg.get("params") or {})
    except LookupError:
        reply["error"] = {"code": -32601, "message": "Method not found"}
    print(json.dumps(reply), flush=True)
