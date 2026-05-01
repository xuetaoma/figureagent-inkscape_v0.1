import io
import json

from inkscape_copilot.mcp_server import handle_request, serve_stdio


def test_mcp_initialize_response() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert response is not None
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "figureagent-inkscape"
    assert "tools" in response["result"]["capabilities"]
    assert "resources" in response["result"]["capabilities"]


def test_mcp_tools_list_exposes_figureagent_tools() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert response is not None
    tools = response["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "get_document_context" in names
    assert "get_ui_state" in names
    assert "validate_action_plan" in names
    assert "start_always_on_worker" in names
    assert "get_always_on_worker_status" in names
    assert "set_target_font_size" in names
    assert "run_publication_qa" in names
    assert "sync_live_document_context" in names
    assert "get_snapshot_paths" in names
    assert "apply_publication_fix" in names
    assert "query_scene_graph" in names
    assert "get_object_details" in names
    assert "rank_edit_targets" in names
    assert "create_polygon" in names
    assert "inputSchema" in tools[0]


def test_mcp_resources_list_exposes_document_resources() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 20, "method": "resources/list"})
    assert response is not None
    resources = response["result"]["resources"]
    uris = {resource["uri"] for resource in resources}
    assert "figureagent://document/context" in uris
    assert "figureagent://document/scene-graph" in uris
    assert "figureagent://publication/qa" in uris
    assert "figureagent://publication/rubric" in uris
    assert "figureagent://publication/feedback" in uris
    assert "figureagent://publication/examples" in uris
    assert "mimeType" in resources[0]


def test_mcp_resources_read_returns_contents() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "resources/read",
            "params": {"uri": "figureagent://document/context"},
        }
    )
    assert response is not None
    contents = response["result"]["contents"]
    assert contents[0]["uri"] == "figureagent://document/context"
    assert contents[0]["mimeType"] == "application/json"
    payload = json.loads(contents[0]["text"])
    assert "objects" in payload


def test_mcp_tools_call_returns_text_content() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "validate_action_plan",
                "arguments": {
                    "plan": {
                        "summary": "No-op",
                        "actions": [],
                        "needs_confirmation": False,
                    }
                },
            },
        }
    )
    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True


def test_mcp_granular_tool_call_returns_preview_plan() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": "set_target_stroke_width",
                "arguments": {"role": "axis_line", "stroke_width_px": 1.25},
            },
        }
    )
    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["apply"] is False
    assert payload["plan"]["actions"][0]["kind"] == "set_object_stroke_width"


def test_mcp_create_polygon_tool_returns_preview_plan() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 35,
            "method": "tools/call",
            "params": {
                "name": "create_polygon",
                "arguments": {
                    "points": [
                        {"x": 10.0, "y": 10.0},
                        {"x": 40.0, "y": 10.0},
                        {"x": 30.0, "y": 35.0},
                    ],
                    "fill_hex": "#f97316",
                },
            },
        }
    )
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["apply"] is False
    assert payload["plan"]["actions"][0]["kind"] == "create_polygon"


def test_mcp_snapshot_paths_tool_returns_metadata() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {"name": "get_snapshot_paths", "arguments": {}},
        }
    )
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert "svg" in payload
    assert "png" in payload


def test_mcp_ui_state_tool_returns_dashboard_shape() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 34,
            "method": "tools/call",
            "params": {"name": "get_ui_state", "arguments": {"event_limit": 5}},
        }
    )
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert "bridge_status" in payload
    assert "document_context" in payload
    assert "pending_jobs" in payload


def test_mcp_query_scene_graph_tool_returns_matches() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {
                "name": "query_scene_graph",
                "arguments": {"role": "panel_label", "limit": 10},
            },
        }
    )
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert "matched_count" in payload


def test_mcp_rank_edit_targets_tool_returns_candidates() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {
                "name": "rank_edit_targets",
                "arguments": {"intent": "top right plot", "limit": 3},
            },
        }
    )
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert "candidates" in payload


def test_mcp_stdio_server_handles_json_lines() -> None:
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )
    stdout = io.StringIO()
    assert serve_stdio(stdin, stdout) == 0
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line["id"] for line in lines] == [1, 2]
    assert "tools" in lines[1]["result"]
