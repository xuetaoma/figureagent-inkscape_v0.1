from __future__ import annotations

import time
from dataclasses import dataclass
from math import inf
from typing import Any, Callable

from . import bridge
from .bridge import (
    append_job,
    clear_planned_step,
    mark_error,
    pending_jobs,
    read_document_context,
    read_events,
    read_execution_result,
    read_planned_step,
    read_session_state,
    read_status,
    reset_state,
    write_execution_result,
    write_planned_step,
)
from .always_on_worker import start_worker, stop_worker, worker_status
from .inkscape_control import trigger_apply_pending_jobs
from .mcp_resources import _document_context_from_payload
from .publication_fixes import publication_fix_suggestions, safe_publication_actions
from .publication_qa import publication_qa
from .schema import Action, ActionPlan, action_plan_json_schema
from .targeting import TargetQuery, resolve_ids_from_snapshot


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class FigureAgentTool:
    name: str
    description: str
    input_schema: JsonDict
    handler: Callable[[JsonDict], JsonDict]

    def to_descriptor(self) -> JsonDict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


EMPTY_INPUT_SCHEMA: JsonDict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}


TARGET_SELECTOR_KEYS = (
    "object_id",
    "object_index",
    "text",
    "role",
    "panel",
    "axis",
    "tag",
    "parent_id",
    "group_id",
    "panel_root_id",
    "label_for",
    "attached_to",
    "text_group_id",
    "glyph_for",
    "include_descendants",
)


def _plan_input_schema() -> JsonDict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "prompt": {"type": "string"},
            "plan": action_plan_json_schema(),
            "source": {"type": "string"},
            "auto_apply": {"type": "boolean"},
            "retry_count": {"type": "integer"},
            "wait_timeout_seconds": {"type": "number"},
        },
        "required": ["prompt", "plan"],
    }


def _target_properties() -> JsonDict:
    return {
        "object_id": {"type": "string"},
        "object_index": {"type": "integer"},
        "text": {"type": "string"},
        "role": {"type": "string"},
        "panel": {"type": "string"},
        "axis": {"type": "string"},
        "tag": {"type": "string"},
        "parent_id": {"type": "string"},
        "group_id": {"type": "string"},
        "panel_root_id": {"type": "string"},
        "label_for": {"type": "string"},
        "attached_to": {"type": "string"},
        "text_group_id": {"type": "string"},
        "glyph_for": {"type": "string"},
        "include_descendants": {"type": "boolean"},
    }


def _action_tool_schema(extra_properties: JsonDict, required: list[str] | None = None) -> JsonDict:
    properties: JsonDict = {
        **_target_properties(),
        **extra_properties,
        "apply": {
            "type": "boolean",
            "description": "When true, dispatch the action to Inkscape. Defaults to false for preview/validation.",
        },
        "prompt": {
            "type": "string",
            "description": "Optional human-readable intent for the queued plan.",
        },
        "wait_timeout_seconds": {"type": "number"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required or [],
    }


def _selector_from_payload(payload: JsonDict) -> JsonDict:
    selector: JsonDict = {}
    for key in TARGET_SELECTOR_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        if key == "object_index" and isinstance(value, int):
            selector[key] = value
        elif key == "include_descendants" and isinstance(value, bool):
            selector[key] = value
        elif isinstance(value, str) and value.strip():
            selector[key] = value.strip()
    if not selector:
        raise ValueError("Tool requires a target selector such as object_id, role, panel, axis, text, or group_id.")
    return selector


def _selector_from_payload_optional(payload: JsonDict) -> JsonDict:
    selector: JsonDict = {}
    for key in TARGET_SELECTOR_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        if key == "object_index" and isinstance(value, int):
            selector[key] = value
        elif key == "include_descendants" and isinstance(value, bool):
            selector[key] = value
        elif isinstance(value, str) and value.strip():
            selector[key] = value.strip()
    return selector


def _plan_for_action(summary: str, kind: str, params: JsonDict) -> ActionPlan:
    action = Action.from_dict({"kind": kind, "params": params})
    return ActionPlan(summary=summary, actions=[action], needs_confirmation=False)


def _preview_or_dispatch(payload: JsonDict, plan: ActionPlan) -> JsonDict:
    if bool(payload.get("apply")):
        return _dispatch_action_plan(
            {
                "prompt": str(payload.get("prompt") or plan.summary),
                "plan": plan.to_dict(),
                "source": "mcp-tool",
                "wait_timeout_seconds": payload.get("wait_timeout_seconds", 30.0),
            }
        )
    return {"ok": True, "apply": False, "plan": plan.to_dict(), "action_count": len(plan.actions)}


def _validate_action_plan(payload: JsonDict) -> JsonDict:
    plan_payload = payload.get("plan")
    if not isinstance(plan_payload, dict):
        raise ValueError("validate_action_plan requires a plan object.")
    plan = ActionPlan.from_dict(plan_payload)
    return {"ok": True, "plan": plan.to_dict(), "action_count": len(plan.actions)}


def _get_document_context(_: JsonDict | None = None) -> JsonDict:
    return {"document_context": read_document_context()}


def _get_bridge_status(_: JsonDict | None = None) -> JsonDict:
    return {
        "status": read_status(),
        "execution_result": read_execution_result(),
        "always_on_worker": worker_status(),
        "pending_jobs": [job.to_dict() for job in pending_jobs()],
    }


def _get_ui_state(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    limit_value = payload.get("event_limit")
    event_limit = int(limit_value) if isinstance(limit_value, int) and limit_value > 0 else 20
    return {
        "ok": True,
        "bridge_status": read_status(),
        "session_state": read_session_state(),
        "document_context": read_document_context(),
        "planned_step": read_planned_step(),
        "execution_result": read_execution_result(),
        "recent_events": read_events(limit=event_limit),
        "pending_jobs": [job.to_dict() for job in pending_jobs()],
        "always_on_worker": worker_status(),
    }


def _sync_live_document_context(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    allow_apply_pending = bool(payload.get("allow_apply_pending"))
    jobs = pending_jobs()
    if jobs and not allow_apply_pending:
        raise RuntimeError(
            "Cannot sync-only while jobs are pending. Call dispatch/apply first, or pass allow_apply_pending=true."
        )
    ok, error = trigger_apply_pending_jobs()
    return {
        "ok": ok,
        "error": error,
        "document_context": read_document_context(),
        "execution_result": read_execution_result(),
    }


def _get_snapshot_paths(_: JsonDict | None = None) -> JsonDict:
    svg_path = bridge.DOCUMENT_SVG_SNAPSHOT_FILE
    png_path = bridge.DOCUMENT_PNG_SNAPSHOT_FILE
    return {
        "ok": True,
        "svg": {
            "path": str(svg_path),
            "exists": svg_path.exists(),
            "size_bytes": svg_path.stat().st_size if svg_path.exists() else 0,
        },
        "png": {
            "path": str(png_path),
            "exists": png_path.exists(),
            "size_bytes": png_path.stat().st_size if png_path.exists() else 0,
        },
    }


def _query_scene_graph(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    context = read_document_context()
    objects = [item for item in context.get("objects", []) if isinstance(item, dict)]
    selector = _selector_from_payload_optional(payload)
    limit_value = payload.get("limit")
    include_objects = payload.get("include_objects")
    limit = int(limit_value) if isinstance(limit_value, int) and limit_value > 0 else 50

    if selector:
        object_ids = resolve_ids_from_snapshot(objects, TargetQuery.from_params(selector))
        id_set = set(object_ids)
        matched_objects = [item for item in objects if str(item.get("object_id") or "") in id_set]
    else:
        matched_objects = objects
        object_ids = [str(item.get("object_id")) for item in matched_objects if item.get("object_id")]

    role_counts: dict[str, int] = {}
    panel_counts: dict[str, int] = {}
    for item in matched_objects:
        role = item.get("role")
        panel = item.get("panel")
        if isinstance(role, str) and role:
            role_counts[role] = role_counts.get(role, 0) + 1
        if isinstance(panel, str) and panel:
            panel_counts[panel] = panel_counts.get(panel, 0) + 1

    result: JsonDict = {
        "ok": True,
        "selector": selector,
        "matched_count": len(matched_objects),
        "object_ids": object_ids[:limit],
        "truncated": len(matched_objects) > limit,
        "role_counts": role_counts,
        "panel_counts": panel_counts,
    }
    if bool(include_objects):
        result["objects"] = matched_objects[:limit]
    return result


def _get_object_details(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    object_id = payload.get("object_id")
    if not isinstance(object_id, str) or not object_id.strip():
        raise ValueError("get_object_details requires object_id.")
    object_id = object_id.strip()
    include_related = bool(payload.get("include_related", True))
    context = read_document_context()
    objects = [item for item in context.get("objects", []) if isinstance(item, dict)]
    target = next((item for item in objects if str(item.get("object_id") or "") == object_id), None)
    if target is None:
        raise ValueError(f"Could not find object_id: {object_id}")

    result: JsonDict = {"ok": True, "object": target}
    if not include_related:
        return result

    relation_keys = (
        "parent_id",
        "group_id",
        "panel_root_id",
        "label_for",
        "attached_to",
        "text_group_id",
        "glyph_for",
    )
    related_ids = {object_id}
    for key in relation_keys:
        value = target.get(key)
        if isinstance(value, str) and value:
            related_ids.add(value)
    for item in objects:
        item_id = str(item.get("object_id") or "")
        if not item_id or item_id == object_id:
            continue
        if any(str(item.get(key) or "") in related_ids for key in relation_keys):
            related_ids.add(item_id)
        if any(str(item.get(key) or "") == object_id for key in relation_keys):
            related_ids.add(item_id)
    result["related_objects"] = [item for item in objects if str(item.get("object_id") or "") in related_ids and str(item.get("object_id") or "") != object_id]
    return result


def _bbox_center(bbox: JsonDict | None) -> tuple[float, float] | None:
    if not isinstance(bbox, dict):
        return None
    try:
        return (
            float(bbox["left"]) + (float(bbox["width"]) / 2.0),
            float(bbox["top"]) + (float(bbox["height"]) / 2.0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _object_area(item: JsonDict) -> float:
    bbox = item.get("bbox")
    if not isinstance(bbox, dict):
        return 0.0
    try:
        return max(0.0, float(bbox.get("width") or 0.0)) * max(0.0, float(bbox.get("height") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _panel_bbox(objects: list[JsonDict], panel: str | None) -> JsonDict | None:
    boxes = [
        item.get("bbox")
        for item in objects
        if isinstance(item.get("bbox"), dict)
        and (not panel or str(item.get("panel") or "").lower() == panel.lower())
        and _object_area(item) < 1_000_000
    ]
    boxes = [box for box in boxes if isinstance(box, dict)]
    if not boxes:
        return None
    left = min(float(box["left"]) for box in boxes)
    top = min(float(box["top"]) for box in boxes)
    right = max(float(box["left"]) + float(box["width"]) for box in boxes)
    bottom = max(float(box["top"]) + float(box["height"]) for box in boxes)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _rank_direction_score(center: tuple[float, float] | None, bounds: JsonDict | None, intent: str) -> tuple[float, list[str]]:
    if center is None or not isinstance(bounds, dict):
        return 0.0, []
    try:
        left = float(bounds["left"])
        top = float(bounds["top"])
        width = max(1.0, float(bounds["width"]))
        height = max(1.0, float(bounds["height"]))
    except (KeyError, TypeError, ValueError):
        return 0.0, []
    x_norm = (center[0] - left) / width
    y_norm = (center[1] - top) / height
    score = 0.0
    reasons: list[str] = []
    if "left" in intent:
        score += max(0.0, 1.0 - x_norm) * 12.0
        reasons.append("matches left-side geometry")
    if "right" in intent:
        score += max(0.0, x_norm) * 12.0
        reasons.append("matches right-side geometry")
    if "top" in intent or "upper" in intent:
        score += max(0.0, 1.0 - y_norm) * 12.0
        reasons.append("matches upper geometry")
    if "bottom" in intent or "lower" in intent:
        score += max(0.0, y_norm) * 12.0
        reasons.append("matches lower geometry")
    return score, reasons


def _intent_role_hints(intent: str) -> set[str]:
    roles: set[str] = set()
    if "panel label" in intent:
        roles.add("panel_label")
        return roles
    if "axis label" in intent or "axis labels" in intent:
        roles.add("axis_label")
        return roles
    if "tick label" in intent or "tick labels" in intent or "number" in intent or "numbers" in intent:
        roles.add("tick_label")
        return roles
    if any(word in intent for word in ("axis", "axes")):
        roles.add("axis_line")
    if "tick" in intent:
        roles.add("axis_tick")
    if any(word in intent for word in ("label", "font", "text", "number")):
        roles.update({"axis_label", "tick_label", "label", "panel_label"})
    if any(word in intent for word in ("plot", "graph", "curve", "panel", "figure")):
        roles.update({"axis_line", "frame", "panel_root", "line_art", "shape"})
    return roles


def _rank_edit_targets(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    intent = str(payload.get("intent") or payload.get("prompt") or "").lower()
    context = read_document_context()
    objects = [item for item in context.get("objects", []) if isinstance(item, dict)]
    selector = _selector_from_payload_optional(payload)
    limit_value = payload.get("limit")
    limit = int(limit_value) if isinstance(limit_value, int) and limit_value > 0 else 10

    if selector and ("object_id" in selector or "object_index" in selector):
        object_ids = resolve_ids_from_snapshot(objects, TargetQuery.from_params(selector))
        id_set = set(object_ids)
        candidates = [item for item in objects if str(item.get("object_id") or "") in id_set]
    else:
        candidates = objects

    panel = selector.get("panel") if isinstance(selector.get("panel"), str) else None
    axis = selector.get("axis") if isinstance(selector.get("axis"), str) else None
    role_hints = _intent_role_hints(intent)
    label_intent = any(word in intent for word in ("label", "text", "font", "number"))
    label_roles = {"axis_label", "tick_label", "label", "panel_label", "layer_label", "text_glyph"}
    bounds = _panel_bbox(objects, panel) or _panel_bbox(objects, None)
    ranked: list[JsonDict] = []

    for item in candidates:
        object_id = str(item.get("object_id") or "")
        if not object_id:
            continue
        role = item.get("role")
        tag = item.get("tag")
        bbox = item.get("bbox")
        center = _bbox_center(bbox if isinstance(bbox, dict) else None)
        area = _object_area(item)
        if area > 1_000_000 and "object_id" not in selector:
            continue
        score = 0.0
        reasons: list[str] = []

        if panel and str(item.get("panel") or "").lower() == panel.lower():
            score += 30.0
            reasons.append(f"matches panel {panel}")
        elif panel:
            score -= 20.0

        if axis and str(item.get("axis") or "").lower() == axis.lower():
            score += 18.0
            reasons.append(f"matches {axis} axis")
        elif axis:
            score -= 40.0

        if isinstance(role, str) and role in role_hints:
            score += 18.0
            reasons.append(f"role {role} matches intent")
        if isinstance(role, str) and role == selector.get("role"):
            score += 25.0
            reasons.append(f"matches requested role {role}")
        elif selector.get("role"):
            score -= 10.0
        if isinstance(tag, str) and tag == selector.get("tag"):
            score += 12.0
            reasons.append(f"matches requested tag {tag}")
        elif selector.get("tag"):
            score -= 4.0

        if label_intent and role in label_roles:
            score += 25.0
            reasons.append("label/text intent prefers text-like objects")
        elif label_intent and role not in label_roles:
            score -= 18.0

        text = str(item.get("text") or "").lower()
        if text and any(token for token in intent.split() if len(token) > 2 and token in text):
            score += 8.0
            reasons.append("text overlaps intent")

        direction_score, direction_reasons = _rank_direction_score(center, bounds, intent)
        score += direction_score
        reasons.extend(direction_reasons)

        if area <= 0 and role not in {"axis_line", "axis_tick", "line_art"}:
            score -= 3.0
        if role == "panel_root" and any(word in intent for word in ("panel", "figure")):
            score += 10.0
            reasons.append("panel/figure intent prefers panel root")
        if role == "axis_line" and any(word in intent for word in ("plot", "graph", "width", "height", "resize")):
            score += 10.0
            reasons.append("plot resize intent prefers axis line")
        if role == "tick_label" and "number" in intent:
            score += 10.0
            reasons.append("number intent prefers tick labels")

        if score <= 0 and selector:
            score = 1.0
            reasons.append("matched explicit selector")
        if score <= 0:
            continue

        ranked.append(
            {
                "object_id": object_id,
                "score": round(score, 3),
                "reasons": reasons[:6],
                "role": role,
                "panel": item.get("panel"),
                "axis": item.get("axis"),
                "tag": tag,
                "text": item.get("text"),
                "bbox": item.get("bbox"),
                "group_id": item.get("group_id"),
                "panel_root_id": item.get("panel_root_id"),
            }
        )

    ranked.sort(key=lambda item: (-float(item["score"]), str(item["object_id"])))
    return {
        "ok": True,
        "intent": intent,
        "selector": selector,
        "candidate_count": len(candidates),
        "ranked_count": len(ranked),
        "candidates": ranked[:limit],
    }


def _reset_bridge_state(_: JsonDict | None = None) -> JsonDict:
    reset_state()
    return {"ok": True, "status": read_status()}


def _queue_action_plan(payload: JsonDict) -> JsonDict:
    prompt = payload.get("prompt")
    plan_payload = payload.get("plan")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("queue_action_plan requires a non-empty prompt.")
    if not isinstance(plan_payload, dict):
        raise ValueError("queue_action_plan requires a plan object.")
    execution_result = read_execution_result()
    if execution_result.get("state") == "dispatched":
        raise RuntimeError("The current step has already been dispatched and is still waiting on Inkscape.")
    if pending_jobs():
        raise RuntimeError("There is already a pending step waiting for Inkscape to apply.")

    plan = ActionPlan.from_dict(plan_payload)
    source = payload.get("source")
    job = append_job(prompt.strip(), plan, source=str(source or "tool"))
    write_planned_step(prompt.strip(), plan, ready_to_apply=True)
    write_execution_result(
        state="dispatched",
        job_id=job.job_id,
        summary=f"Dispatched {job.job_id} to Inkscape for execution.",
    )
    return {"ok": True, "job": job.to_dict()}


def _apply_pending_jobs(_: JsonDict | None = None) -> JsonDict:
    ok, error = trigger_apply_pending_jobs()
    return {"ok": ok, "error": error}


def _start_always_on_worker(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    interval = payload.get("interval_seconds")
    document_name = payload.get("document_name")
    document_id = payload.get("document_id")
    worker_origin = payload.get("worker_origin")
    return start_worker(
        interval_seconds=float(interval) if isinstance(interval, (int, float)) else 0.75,
        document_name=str(document_name) if isinstance(document_name, str) and document_name else None,
        document_id=str(document_id) if isinstance(document_id, str) and document_id else None,
        worker_origin=str(worker_origin) if isinstance(worker_origin, str) and worker_origin else "tool",
    )


def _stop_always_on_worker(_: JsonDict | None = None) -> JsonDict:
    return stop_worker()


def _get_always_on_worker_status(_: JsonDict | None = None) -> JsonDict:
    return worker_status()


def _select_targets(payload: JsonDict) -> JsonDict:
    params = _selector_from_payload(payload)
    plan = _plan_for_action("Select matching targets.", "select_targets", params)
    return _preview_or_dispatch(payload, plan)


def _set_target_font_size(payload: JsonDict) -> JsonDict:
    font_size = payload.get("font_size_px")
    if not isinstance(font_size, (int, float)):
        raise ValueError("set_target_font_size requires numeric font_size_px.")
    params = {**_selector_from_payload(payload), "font_size_px": float(font_size)}
    plan = _plan_for_action("Set target font size.", "set_object_font_size", params)
    return _preview_or_dispatch(payload, plan)


def _set_target_stroke_width(payload: JsonDict) -> JsonDict:
    stroke_width = payload.get("stroke_width_px")
    if not isinstance(stroke_width, (int, float)):
        raise ValueError("set_target_stroke_width requires numeric stroke_width_px.")
    params = {**_selector_from_payload(payload), "stroke_width_px": float(stroke_width)}
    plan = _plan_for_action("Set target stroke width.", "set_object_stroke_width", params)
    return _preview_or_dispatch(payload, plan)


def _move_targets(payload: JsonDict) -> JsonDict:
    delta_x = payload.get("delta_x_px")
    delta_y = payload.get("delta_y_px")
    if not isinstance(delta_x, (int, float)) or not isinstance(delta_y, (int, float)):
        raise ValueError("move_targets requires numeric delta_x_px and delta_y_px.")
    params = {**_selector_from_payload(payload), "delta_x_px": float(delta_x), "delta_y_px": float(delta_y)}
    plan = _plan_for_action("Move matching targets.", "move_object", params)
    return _preview_or_dispatch(payload, plan)


def _polygon_points_from_payload(payload: JsonDict) -> list[JsonDict] | None:
    points = payload.get("points")
    if points is None:
        return None
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("create_polygon requires points with at least 3 {x, y} objects.")
    normalized: list[JsonDict] = []
    for point in points:
        if not isinstance(point, dict) or not all(isinstance(point.get(key), (int, float)) for key in ("x", "y")):
            raise ValueError("create_polygon points must be objects with numeric x and y.")
        normalized.append({"x": float(point["x"]), "y": float(point["y"])})
    return normalized


def _create_polygon_tool(payload: JsonDict) -> JsonDict:
    points = _polygon_points_from_payload(payload)
    params: JsonDict = {
        "fill_hex": payload.get("fill_hex") if isinstance(payload.get("fill_hex"), str) else "#2563eb",
        "stroke_hex": payload.get("stroke_hex") if isinstance(payload.get("stroke_hex"), str) else None,
        "stroke_width_px": float(payload["stroke_width_px"]) if isinstance(payload.get("stroke_width_px"), (int, float)) else None,
    }
    if points is not None:
        params.update({"points": points, "cx": None, "cy": None, "radius": None, "count": None, "degrees": None})
    else:
        if not all(isinstance(payload.get(key), (int, float)) for key in ("cx", "cy", "radius", "count")):
            raise ValueError("create_polygon requires either points or numeric cx, cy, radius, and count.")
        params.update(
            {
                "cx": float(payload["cx"]),
                "cy": float(payload["cy"]),
                "radius": float(payload["radius"]),
                "count": int(payload["count"]),
                "degrees": float(payload.get("degrees") or 0.0),
                "points": None,
            }
        )
    plan = _plan_for_action("Create a polygon.", "create_polygon", params)
    return _preview_or_dispatch(payload, plan)


def _resize_plot_width(payload: JsonDict) -> JsonDict:
    width = payload.get("width")
    percent = payload.get("percent")
    if not isinstance(width, (int, float)) and not isinstance(percent, (int, float)):
        raise ValueError("resize_plot_width requires numeric width or percent.")
    params = _selector_from_payload(payload)
    if isinstance(width, (int, float)):
        params["width"] = float(width)
    if isinstance(percent, (int, float)):
        params["percent"] = float(percent)
    plan = _plan_for_action("Resize plot width while preserving tick/text styling.", "resize_plot_width", params)
    return _preview_or_dispatch(payload, plan)


def _resize_plot_height(payload: JsonDict) -> JsonDict:
    height = payload.get("height")
    percent = payload.get("percent")
    if not isinstance(height, (int, float)) and not isinstance(percent, (int, float)):
        raise ValueError("resize_plot_height requires numeric height or percent.")
    params = _selector_from_payload(payload)
    if isinstance(height, (int, float)):
        params["height"] = float(height)
    if isinstance(percent, (int, float)):
        params["percent"] = float(percent)
    plan = _plan_for_action("Resize plot height while preserving tick/text styling.", "resize_plot_height", params)
    return _preview_or_dispatch(payload, plan)


def _set_tick_length(payload: JsonDict) -> JsonDict:
    length = payload.get("length_px")
    if not isinstance(length, (int, float)):
        raise ValueError("set_tick_length requires numeric length_px.")
    params = {**_selector_from_payload(payload), "length_px": float(length)}
    plan = _plan_for_action("Set tick length.", "set_tick_length", params)
    return _preview_or_dispatch(payload, plan)


def _set_tick_thickness(payload: JsonDict) -> JsonDict:
    stroke_width = payload.get("stroke_width_px")
    if not isinstance(stroke_width, (int, float)):
        raise ValueError("set_tick_thickness requires numeric stroke_width_px.")
    params = {**_selector_from_payload(payload), "stroke_width_px": float(stroke_width)}
    plan = _plan_for_action("Set tick thickness.", "set_tick_thickness", params)
    return _preview_or_dispatch(payload, plan)


def _run_publication_qa(_: JsonDict | None = None) -> JsonDict:
    document = _document_context_from_payload(read_document_context())
    qa = publication_qa(document)
    return {
        "ok": True,
        "qa": qa,
        "publication_fix_suggestions": publication_fix_suggestions(document, qa),
    }


def _apply_publication_fixes(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    document = _document_context_from_payload(read_document_context())
    qa = publication_qa(document)
    actions = safe_publication_actions(document, qa)
    plan = ActionPlan(
        summary="Apply safe publication QA fixes.",
        actions=actions,
        needs_confirmation=False,
    )
    return _preview_or_dispatch(payload, plan)


def _apply_publication_fix(payload: JsonDict | None = None) -> JsonDict:
    payload = payload or {}
    document = _document_context_from_payload(read_document_context())
    qa = publication_qa(document)
    suggestions = publication_fix_suggestions(document, qa)

    selected: JsonDict | None = None
    finding_index = payload.get("finding_index")
    rule_id = payload.get("rule_id")
    if isinstance(finding_index, int):
        if finding_index < 0 or finding_index >= len(suggestions):
            raise ValueError("finding_index is out of range.")
        candidate = suggestions[finding_index]
        if isinstance(candidate, dict):
            selected = candidate
    elif isinstance(rule_id, str) and rule_id.strip():
        for candidate in suggestions:
            if isinstance(candidate, dict) and candidate.get("rule_id") == rule_id.strip():
                selected = candidate
                break
    else:
        raise ValueError("apply_publication_fix requires finding_index or rule_id.")

    if not selected:
        raise ValueError("Could not find the requested publication QA finding.")
    action_payload = selected.get("safe_action")
    if not isinstance(action_payload, dict):
        raise ValueError("The requested publication QA finding does not have an auto-applicable safe action.")

    action = Action.from_dict(action_payload)
    plan = ActionPlan(
        summary=f"Apply publication QA fix {selected.get('rule_id') or finding_index}.",
        actions=[action],
        needs_confirmation=False,
    )
    return _preview_or_dispatch(payload, plan)


def _job_finished(job_id: str) -> tuple[bool, bool, str]:
    result = read_execution_result()
    if result.get("job_id") == job_id and result.get("state") == "applied":
        return True, True, str(result.get("summary") or f"Applied {job_id}.")
    if result.get("job_id") == job_id and result.get("state") == "error":
        return True, False, str(result.get("error") or f"Failed to apply {job_id}.")

    status = read_status()
    if job_id in set(status.get("applied_job_ids") or []):
        return True, True, str(result.get("summary") or f"Applied {job_id}.")
    if job_id in set(status.get("failed_job_ids") or []):
        return True, False, str(status.get("last_error") or result.get("error") or f"Failed to apply {job_id}.")
    return False, False, ""


def _wait_for_job(job_id: str, timeout_seconds: float) -> tuple[bool, bool, str]:
    deadline = time.time() + max(0.1, timeout_seconds)
    while time.time() < deadline:
        finished, ok, message = _job_finished(job_id)
        if finished:
            return True, ok, message
        time.sleep(0.25)
    finished, ok, message = _job_finished(job_id)
    if finished:
        return True, ok, message
    return False, False, f"Timed out waiting for Inkscape to apply {job_id}."


def _queue_and_apply_action_plan(payload: JsonDict) -> JsonDict:
    queued = _queue_action_plan(payload)
    job_id = queued.get("job", {}).get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("Queued job did not return a job id.")

    retry_count = payload.get("retry_count")
    wait_timeout_seconds = payload.get("wait_timeout_seconds")
    retries = max(1, int(retry_count) if isinstance(retry_count, int) else 2)
    timeout = float(wait_timeout_seconds) if isinstance(wait_timeout_seconds, (int, float)) else 30.0

    apply_attempts: list[JsonDict] = []
    last_error: str | None = None
    always_on = worker_status()
    if always_on.get("running"):
        finished, job_ok, job_message = _wait_for_job(job_id, timeout)
        if finished:
            return {
                "ok": job_ok,
                "job_id": job_id,
                "queued": queued,
                "apply_attempts": [{"attempt": 1, "ok": True, "worker": "always_on"}],
                "message": job_message,
            }
        last_error = job_message

    for attempt in range(retries):
        apply_result = _apply_pending_jobs({})
        apply_attempts.append({"attempt": attempt + 1, **apply_result})
        if not apply_result["ok"]:
            last_error = str(apply_result.get("error") or "Could not trigger Inkscape apply.")
            continue

        finished, job_ok, job_message = _wait_for_job(job_id, timeout if attempt == 0 else max(timeout, 45.0))
        if finished:
            return {
                "ok": job_ok,
                "job_id": job_id,
                "queued": queued,
                "apply_attempts": apply_attempts,
                "message": job_message,
            }
        last_error = job_message

    error_text = last_error or "Could not dispatch planned step to Inkscape."
    mark_error(job_id, error_text)
    write_execution_result(state="error", job_id=job_id, error=error_text)
    return {
        "ok": False,
        "job_id": job_id,
        "queued": queued,
        "apply_attempts": apply_attempts,
        "message": error_text,
    }


def _dispatch_action_plan(payload: JsonDict) -> JsonDict:
    return _queue_and_apply_action_plan(payload)



def _clear_planned_step(_: JsonDict | None = None) -> JsonDict:
    clear_planned_step()
    return {"ok": True}


def tool_registry() -> dict[str, FigureAgentTool]:
    tools = [
        FigureAgentTool(
            name="get_document_context",
            description="Read the latest structured Inkscape document context and rendered snapshot metadata.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _get_document_context(payload),
        ),
        FigureAgentTool(
            name="get_bridge_status",
            description="Read FigureAgent bridge status, execution result, and pending jobs.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _get_bridge_status(payload),
        ),
        FigureAgentTool(
            name="get_ui_state",
            description="Read the aggregate FigureAgent UI/dashboard state used by thin clients.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "event_limit": {
                        "type": "integer",
                        "description": "Maximum number of recent bridge events to include.",
                    }
                },
            },
            handler=lambda payload: _get_ui_state(payload),
        ),
        FigureAgentTool(
            name="sync_live_document_context",
            description="Ask Inkscape to refresh the current document context and rendered snapshots. Refuses to run while jobs are pending unless allow_apply_pending is true.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "allow_apply_pending": {
                        "type": "boolean",
                        "description": "When true, pending queued jobs may be applied as part of the sync.",
                    }
                },
            },
            handler=lambda payload: _sync_live_document_context(payload),
        ),
        FigureAgentTool(
            name="get_snapshot_paths",
            description="Return local paths and existence metadata for the latest SVG and PNG snapshots.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _get_snapshot_paths(payload),
        ),
        FigureAgentTool(
            name="query_scene_graph",
            description="Search the latest scene graph by semantic selector and return matching object IDs, counts, and optional object payloads.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    **_target_properties(),
                    "limit": {"type": "integer"},
                    "include_objects": {"type": "boolean"},
                },
            },
            handler=lambda payload: _query_scene_graph(payload),
        ),
        FigureAgentTool(
            name="get_object_details",
            description="Read one scene-graph object by object_id, optionally including related/attached/grouped objects.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "object_id": {"type": "string"},
                    "include_related": {"type": "boolean"},
                },
                "required": ["object_id"],
            },
            handler=lambda payload: _get_object_details(payload),
        ),
        FigureAgentTool(
            name="rank_edit_targets",
            description="Rank likely edit targets for a natural-language intent using semantic selectors, panel/axis hints, geometry hints, and object roles.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    **_target_properties(),
                    "intent": {"type": "string"},
                    "prompt": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            handler=lambda payload: _rank_edit_targets(payload),
        ),
        FigureAgentTool(
            name="validate_action_plan",
            description="Validate a structured FigureAgent action plan without queuing or applying it.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"plan": action_plan_json_schema()},
                "required": ["plan"],
            },
            handler=_validate_action_plan,
        ),
        FigureAgentTool(
            name="select_targets",
            description="Preview or apply a semantic selection action for matching document objects.",
            input_schema=_action_tool_schema({}),
            handler=_select_targets,
        ),
        FigureAgentTool(
            name="set_target_font_size",
            description="Preview or apply a font-size edit to objects selected by semantic target fields.",
            input_schema=_action_tool_schema({"font_size_px": {"type": "number"}}, required=["font_size_px"]),
            handler=_set_target_font_size,
        ),
        FigureAgentTool(
            name="set_target_stroke_width",
            description="Preview or apply a stroke-width edit to objects selected by semantic target fields.",
            input_schema=_action_tool_schema({"stroke_width_px": {"type": "number"}}, required=["stroke_width_px"]),
            handler=_set_target_stroke_width,
        ),
        FigureAgentTool(
            name="move_targets",
            description="Preview or apply a relative move to objects selected by semantic target fields.",
            input_schema=_action_tool_schema(
                {"delta_x_px": {"type": "number"}, "delta_y_px": {"type": "number"}},
                required=["delta_x_px", "delta_y_px"],
            ),
            handler=_move_targets,
        ),
        FigureAgentTool(
            name="create_polygon",
            description="Preview or apply polygon creation. Use points for custom polygons, or cx/cy/radius/count for regular polygons.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                            "required": ["x", "y"],
                        },
                    },
                    "cx": {"type": "number"},
                    "cy": {"type": "number"},
                    "radius": {"type": "number"},
                    "count": {"type": "integer"},
                    "degrees": {"type": "number"},
                    "fill_hex": {"type": "string"},
                    "stroke_hex": {"type": "string"},
                    "stroke_width_px": {"type": "number"},
                    "apply": {"type": "boolean"},
                    "prompt": {"type": "string"},
                    "wait_timeout_seconds": {"type": "number"},
                },
            },
            handler=_create_polygon_tool,
        ),
        FigureAgentTool(
            name="resize_plot_width",
            description="Preview or apply semantic plot-width resizing while preserving tick/text visual sizes.",
            input_schema=_action_tool_schema({"width": {"type": "number"}, "percent": {"type": "number"}}),
            handler=_resize_plot_width,
        ),
        FigureAgentTool(
            name="resize_plot_height",
            description="Preview or apply semantic plot-height resizing while preserving tick/text visual sizes.",
            input_schema=_action_tool_schema({"height": {"type": "number"}, "percent": {"type": "number"}}),
            handler=_resize_plot_height,
        ),
        FigureAgentTool(
            name="set_tick_length",
            description="Preview or apply tick-length normalization for targeted axis ticks.",
            input_schema=_action_tool_schema({"length_px": {"type": "number"}}, required=["length_px"]),
            handler=_set_tick_length,
        ),
        FigureAgentTool(
            name="set_tick_thickness",
            description="Preview or apply tick stroke-width normalization for targeted axis ticks.",
            input_schema=_action_tool_schema({"stroke_width_px": {"type": "number"}}, required=["stroke_width_px"]),
            handler=_set_tick_thickness,
        ),
        FigureAgentTool(
            name="run_publication_qa",
            description="Run publication-quality QA on the latest document context and return safe fix suggestions.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _run_publication_qa(payload),
        ),
        FigureAgentTool(
            name="apply_publication_fixes",
            description="Preview or apply safe publication QA fixes from the latest document context.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "apply": {"type": "boolean"},
                    "prompt": {"type": "string"},
                    "wait_timeout_seconds": {"type": "number"},
                },
            },
            handler=lambda payload: _apply_publication_fixes(payload),
        ),
        FigureAgentTool(
            name="apply_publication_fix",
            description="Preview or apply one safe publication QA fix by finding_index or rule_id.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "finding_index": {"type": "integer"},
                    "rule_id": {"type": "string"},
                    "apply": {"type": "boolean"},
                    "prompt": {"type": "string"},
                    "wait_timeout_seconds": {"type": "number"},
                },
            },
            handler=lambda payload: _apply_publication_fix(payload),
        ),
        FigureAgentTool(
            name="queue_action_plan",
            description="Queue a validated action plan for the Inkscape worker.",
            input_schema=_plan_input_schema(),
            handler=_queue_action_plan,
        ),
        FigureAgentTool(
            name="apply_pending_jobs",
            description="Trigger Inkscape to apply queued FigureAgent jobs.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _apply_pending_jobs(payload),
        ),
        FigureAgentTool(
            name="start_always_on_worker",
            description="Start the background worker that watches for queued jobs and asks Inkscape to apply them automatically.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "interval_seconds": {
                        "type": "number",
                        "description": "Polling interval for queued jobs. Defaults to 0.75 seconds.",
                    },
                    "document_name": {
                        "type": "string",
                        "description": "Optional Inkscape document name to attach the worker session to.",
                    },
                    "document_id": {
                        "type": "string",
                        "description": "Optional document/session fingerprint from the Inkscape extension.",
                    },
                    "worker_origin": {
                        "type": "string",
                        "description": "Optional origin label such as tool, cli, mcp, or inkscape-extension.",
                    },
                },
            },
            handler=_start_always_on_worker,
        ),
        FigureAgentTool(
            name="stop_always_on_worker",
            description="Stop the background queue-watching FigureAgent worker.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _stop_always_on_worker(payload),
        ),
        FigureAgentTool(
            name="get_always_on_worker_status",
            description="Read whether the background queue-watching FigureAgent worker is running.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _get_always_on_worker_status(payload),
        ),
        FigureAgentTool(
            name="queue_and_apply_action_plan",
            description="Queue a validated action plan and request Inkscape to apply it.",
            input_schema=_plan_input_schema(),
            handler=_queue_and_apply_action_plan,
        ),
        FigureAgentTool(
            name="dispatch_action_plan",
            description="Queue, trigger, and wait for a validated action plan to finish applying in Inkscape.",
            input_schema=_plan_input_schema(),
            handler=_dispatch_action_plan,
        ),
        FigureAgentTool(
            name="clear_planned_step",
            description="Clear the current planned step without resetting the whole bridge.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _clear_planned_step(payload),
        ),
        FigureAgentTool(
            name="reset_bridge_state",
            description="Clear queued jobs and reset FigureAgent bridge state.",
            input_schema=EMPTY_INPUT_SCHEMA,
            handler=lambda payload: _reset_bridge_state(payload),
        ),
    ]
    return {tool.name: tool for tool in tools}


def list_tools() -> list[JsonDict]:
    return [tool.to_descriptor() for tool in tool_registry().values()]


def call_tool(name: str, payload: JsonDict | None = None) -> JsonDict:
    registry = tool_registry()
    if name not in registry:
        raise ValueError(f"Unknown FigureAgent tool: {name}")
    return registry[name].handler(payload or {})
