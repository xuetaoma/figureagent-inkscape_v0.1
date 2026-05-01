from inkscape_copilot.schema import ActionPlan
from inkscape_copilot.tools import call_tool, list_tools


def test_tool_registry_exposes_mcp_shaped_descriptors() -> None:
    tools = list_tools()
    names = {tool["name"] for tool in tools}
    assert "get_document_context" in names
    assert "get_ui_state" in names
    assert "validate_action_plan" in names
    assert "queue_and_apply_action_plan" in names
    assert "start_always_on_worker" in names
    assert "stop_always_on_worker" in names
    assert "get_always_on_worker_status" in names
    assert "select_targets" in names
    assert "set_target_font_size" in names
    assert "resize_plot_width" in names
    assert "run_publication_qa" in names
    assert "sync_live_document_context" in names
    assert "get_snapshot_paths" in names
    assert "apply_publication_fix" in names
    assert "query_scene_graph" in names
    assert "get_object_details" in names
    assert "rank_edit_targets" in names
    assert "create_polygon" in names
    for tool in tools:
        assert isinstance(tool["description"], str)
        assert tool["input_schema"]["type"] == "object"


def test_validate_action_plan_tool_accepts_action_plan_payload() -> None:
    plan = ActionPlan(summary="No-op test plan", actions=[], needs_confirmation=False)
    result = call_tool("validate_action_plan", {"plan": plan.to_dict()})
    assert result["ok"] is True
    assert result["action_count"] == 0


def test_unknown_tool_is_rejected() -> None:
    try:
        call_tool("missing_tool", {})
    except ValueError as exc:
        assert "Unknown FigureAgent tool" in str(exc)
    else:
        raise AssertionError("Expected unknown tools to be rejected.")


def test_granular_tool_previews_action_plan_by_default() -> None:
    result = call_tool(
        "set_target_font_size",
        {"role": "axis_label", "panel": "a", "font_size_px": 13.333},
    )
    assert result["ok"] is True
    assert result["apply"] is False
    assert result["action_count"] == 1
    action = result["plan"]["actions"][0]
    assert action["kind"] == "set_object_font_size"
    assert action["params"]["role"] == "axis_label"
    assert action["params"]["panel"] == "a"


def test_create_polygon_tool_previews_custom_points() -> None:
    result = call_tool(
        "create_polygon",
        {
            "points": [
                {"x": 10.0, "y": 10.0},
                {"x": 40.0, "y": 10.0},
                {"x": 30.0, "y": 35.0},
            ],
            "fill_hex": "#f97316",
        },
    )
    assert result["ok"] is True
    assert result["apply"] is False
    action = result["plan"]["actions"][0]
    assert action["kind"] == "create_polygon"
    assert action["params"]["points"][2] == {"x": 30.0, "y": 35.0}


def test_publication_qa_tool_returns_findings_shape() -> None:
    result = call_tool("run_publication_qa", {})
    assert result["ok"] is True
    assert "qa" in result
    assert "publication_fix_suggestions" in result


def test_get_snapshot_paths_returns_svg_and_png_metadata() -> None:
    result = call_tool("get_snapshot_paths", {})
    assert result["ok"] is True
    assert "path" in result["svg"]
    assert "exists" in result["svg"]
    assert "path" in result["png"]
    assert "exists" in result["png"]


def test_get_ui_state_returns_dashboard_shape() -> None:
    result = call_tool("get_ui_state", {"event_limit": 5})
    assert result["ok"] is True
    assert "bridge_status" in result
    assert "session_state" in result
    assert "document_context" in result
    assert "planned_step" in result
    assert "execution_result" in result
    assert "recent_events" in result
    assert "pending_jobs" in result


def test_query_scene_graph_returns_counts() -> None:
    result = call_tool("query_scene_graph", {"role": "axis_label", "limit": 5})
    assert result["ok"] is True
    assert "matched_count" in result
    assert "object_ids" in result
    assert "role_counts" in result


def test_rank_edit_targets_returns_candidates_shape() -> None:
    result = call_tool("rank_edit_targets", {"intent": "top right plot", "limit": 3})
    assert result["ok"] is True
    assert "candidate_count" in result
    assert "ranked_count" in result
    assert isinstance(result["candidates"], list)
