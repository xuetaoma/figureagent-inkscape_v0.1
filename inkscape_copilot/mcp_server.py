from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .mcp_resources import list_resources, read_resource
from .tools import call_tool, list_tools


JsonDict = dict[str, Any]
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "figureagent-inkscape"
SERVER_VERSION = "0.1.0"


def _jsonrpc_result(request_id: Any, result: JsonDict) -> JsonDict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> JsonDict:
    error: JsonDict = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _mcp_tool_descriptor(tool: JsonDict) -> JsonDict:
    return {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": tool["input_schema"],
    }


def _text_tool_result(payload: JsonDict, *, is_error: bool = False) -> JsonDict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, indent=2, ensure_ascii=False),
            }
        ],
        "isError": is_error,
    }


def initialize_result(params: JsonDict | None = None) -> JsonDict:
    params = params if isinstance(params, dict) else {}
    requested_version = params.get("protocolVersion")
    return {
        "protocolVersion": str(requested_version or DEFAULT_PROTOCOL_VERSION),
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
        "instructions": (
            "FigureAgent for Inkscape exposes tools for inspecting the current "
            "document bridge state, reading document/snapshot resources, validating "
            "action plans, and requesting the Inkscape worker to apply queued "
            "figure-editing actions."
        ),
    }


def handle_request(message: JsonDict) -> JsonDict | None:
    if not isinstance(message, dict):
        return _jsonrpc_error(None, -32600, "Invalid JSON-RPC message.")

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params")

    if not isinstance(method, str):
        return _jsonrpc_error(request_id, -32600, "JSON-RPC message is missing method.")

    # Notifications intentionally do not receive responses.
    if method.startswith("notifications/") or method in {"initialized"}:
        return None

    try:
        if method == "initialize":
            return _jsonrpc_result(request_id, initialize_result(params if isinstance(params, dict) else {}))

        if method == "ping":
            return _jsonrpc_result(request_id, {})

        if method == "tools/list":
            return _jsonrpc_result(
                request_id,
                {"tools": [_mcp_tool_descriptor(tool) for tool in list_tools()]},
            )

        if method == "resources/list":
            return _jsonrpc_result(request_id, {"resources": list_resources()})

        if method == "resources/read":
            if not isinstance(params, dict):
                return _jsonrpc_error(request_id, -32602, "resources/read requires params.")
            uri = params.get("uri")
            if not isinstance(uri, str) or not uri:
                return _jsonrpc_error(request_id, -32602, "resources/read requires params.uri.")
            try:
                content = read_resource(uri)
            except Exception as exc:
                return _jsonrpc_error(request_id, -32602, f"{type(exc).__name__}: {exc}")
            return _jsonrpc_result(request_id, {"contents": [content]})

        if method == "tools/call":
            if not isinstance(params, dict):
                return _jsonrpc_error(request_id, -32602, "tools/call requires params.")
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not name:
                return _jsonrpc_error(request_id, -32602, "tools/call requires params.name.")
            if not isinstance(arguments, dict):
                return _jsonrpc_error(request_id, -32602, "tools/call params.arguments must be an object.")
            try:
                result = call_tool(name, arguments)
            except Exception as exc:
                return _jsonrpc_result(
                    request_id,
                    _text_tool_result(
                        {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                        is_error=True,
                    ),
                )
            return _jsonrpc_result(request_id, _text_tool_result(result))

        return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        return _jsonrpc_error(request_id, -32603, f"Internal error: {type(exc).__name__}: {exc}")


def serve_stdio(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _jsonrpc_error(None, -32700, f"Parse error: {exc}")
        else:
            response = handle_request(message)
        if response is None:
            continue
        stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def main() -> int:
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
