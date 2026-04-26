from __future__ import annotations

import json
import os
import re
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from .planner import DocumentContext
from .publication_fixes import PUBLICATION_RUBRIC_SUMMARY, publication_fix_suggestions, safe_publication_actions
from .publication_memory import publication_memory_summary
from .publication_qa import publication_qa
from .schema import Action, ActionPlan, action_plan_json_schema
from .templates import build_layer_schematic_plan, build_publication_figure_plan


DEFAULT_PROVIDER = "openai"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1/responses"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
_ENV_LOADED = False


class OpenAIPlannerError(RuntimeError):
    """Raised when the remote planner fails."""


def _candidate_env_paths() -> list[Path]:
    package_dir = Path(__file__).resolve().parent
    project_root = os.environ.get("INKSCAPE_COPILOT_PROJECT_ROOT")
    explicit_env_file = os.environ.get("INKSCAPE_COPILOT_ENV_FILE")
    paths = [
        Path(explicit_env_file).expanduser() if explicit_env_file else None,
        Path(project_root).expanduser() / ".env" if project_root else None,
        Path.cwd() / ".env",
        package_dir.parent / ".env",
        package_dir / ".env",
        Path.home() / "Desktop/inkscape-copilot/.env",
    ]
    home = os.environ.get("INKSCAPE_COPILOT_HOME")
    if home:
        paths.append(Path(home) / ".env")
    return [path for path in paths if path is not None]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _load_local_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    seen: set[Path] = set()
    for path in _candidate_env_paths():
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            parsed = _parse_env_line(line)
            if not parsed:
                continue
            key, value = parsed
            current = os.environ.get(key)
            if not current or _looks_like_placeholder(current):
                os.environ[key] = value


def _looks_like_placeholder(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    if normalized in {
        "your_actual_api_key_here",
        "your_key_here",
        "replace_me",
    }:
        return True
    if normalized.startswith("your_") or normalized.startswith("your-"):
        return True
    if normalized.startswith("sk-") and "here" in normalized:
        return True
    return False


def _launchctl_env(name: str) -> str | None:
    try:
        result = subprocess.run(
            ["launchctl", "getenv", name],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return value or None


def _provider() -> str:
    _load_local_env()
    value = os.environ.get("INKSCAPE_COPILOT_PROVIDER") or os.environ.get("AI_PROVIDER") or DEFAULT_PROVIDER
    normalized = value.strip().lower()
    if normalized in {"deepseek", "openai"}:
        return normalized
    return DEFAULT_PROVIDER


def _resolve_api_key(explicit_api_key: str | None, provider: str) -> str | None:
    _load_local_env()
    if explicit_api_key and not _looks_like_placeholder(explicit_api_key):
        return explicit_api_key

    key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"

    env_value = os.environ.get(key_name)
    if env_value and not _looks_like_placeholder(env_value):
        return env_value

    launchctl_value = _launchctl_env(key_name)
    if launchctl_value and not _looks_like_placeholder(launchctl_value):
        return launchctl_value

    if env_value:
        return env_value
    return explicit_api_key


def _resolve_ca_bundle() -> str | None:
    _load_local_env()
    candidates = [
        os.environ.get("OPENAI_CA_BUNDLE"),
        os.environ.get("SSL_CERT_FILE"),
        os.environ.get("REQUESTS_CA_BUNDLE"),
        "/etc/ssl/cert.pem",
        "/private/etc/ssl/cert.pem",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _ssl_context() -> ssl.SSLContext:
    cafile = _resolve_ca_bundle()
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def _extract_output_text(payload: dict) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        raise OpenAIPlannerError("Responses API payload did not include an output array.")

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content_item in item.get("content", []):
            if isinstance(content_item, dict) and content_item.get("type") == "output_text":
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)
    if not parts:
        raise OpenAIPlannerError("Responses API payload did not include output_text content.")
    return "\n".join(parts).strip()


def _json_error_snippet(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if len(compact) > limit:
        return compact[:limit] + "..."
    return compact


def _allows_document_resize(prompt: str) -> bool:
    normalized = prompt.lower()
    size_words = ("size", "resize", "set", "change", "make")
    document_words = ("page", "canvas", "document", "artboard", "sheet")
    explicit_dimensions = bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:px|pixel|pixels)?\s*(?:x|×|by)\s*\d+(?:\.\d+)?\s*(?:px|pixel|pixels)?\b", normalized))
    return any(word in normalized for word in document_words) and (
        explicit_dimensions or any(word in normalized for word in size_words)
    )


def _guard_document_resize(prompt: str, plan: ActionPlan) -> ActionPlan:
    if _allows_document_resize(prompt):
        return plan
    filtered_actions = [action for action in plan.actions if action.kind != "set_document_size"]
    if len(filtered_actions) == len(plan.actions):
        return plan
    summary = f"{plan.summary} Document resizing was skipped because the prompt did not explicitly request a page/canvas size change."
    return ActionPlan(summary=summary, actions=filtered_actions, needs_confirmation=plan.needs_confirmation)


CREATE_ACTION_KINDS = {
    "create_arrow",
    "create_bracket",
    "create_circle",
    "create_ellipse",
    "create_layer_bar",
    "create_line",
    "create_polygon",
    "create_rectangle",
    "create_repeated_circles",
    "create_rounded_rectangle",
    "create_star",
    "create_text",
}


def _action_bbox(action: Action) -> tuple[float, float, float, float] | None:
    params = action.params

    def number(key: str) -> float | None:
        value = params.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    if action.kind in {"create_rectangle", "create_rounded_rectangle", "create_layer_bar"}:
        x = number("x")
        y = number("y")
        width = number("width")
        height = number("height")
        if None not in (x, y, width, height):
            return (x, y, x + width, y + height)
    if action.kind == "create_circle":
        cx = number("cx")
        cy = number("cy")
        radius = number("radius")
        if None not in (cx, cy, radius):
            return (cx - radius, cy - radius, cx + radius, cy + radius)
    if action.kind == "create_ellipse":
        cx = number("cx")
        cy = number("cy")
        width = number("width")
        height = number("height")
        if None not in (cx, cy, width, height):
            return (cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)
    if action.kind in {"create_line", "create_arrow"}:
        x1 = number("x1")
        y1 = number("y1")
        x2 = number("x2")
        y2 = number("y2")
        if None not in (x1, y1, x2, y2):
            return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    if action.kind == "create_bracket":
        x = number("x")
        y1 = number("y1")
        y2 = number("y2")
        width = number("width")
        if None not in (x, y1, y2, width):
            return (min(x, x + width), min(y1, y2), max(x, x + width), max(y1, y2))
    if action.kind == "create_repeated_circles":
        x = number("x")
        y = number("y")
        radius = number("radius")
        count = number("count")
        spacing_x = number("spacing_x")
        spacing_y = number("spacing_y") or 0.0
        if None not in (x, y, radius, count, spacing_x):
            last_x = x + (max(0, int(count) - 1) * spacing_x)
            last_y = y + (max(0, int(count) - 1) * spacing_y)
            return (min(x, last_x) - radius, min(y, last_y) - radius, max(x, last_x) + radius, max(y, last_y) + radius)
    if action.kind in {"create_polygon", "create_star"}:
        cx = number("cx")
        cy = number("cy")
        radius = number("radius")
        if None not in (cx, cy, radius):
            return (cx - radius, cy - radius, cx + radius, cy + radius)
    if action.kind == "create_text":
        x = number("x")
        y = number("y")
        font_size = number("font_size_px") or 12.0
        text = str(params.get("text") or "")
        if None not in (x, y):
            width = max(font_size, len(text) * font_size * 0.6)
            return (x, y - font_size, x + width, y + font_size * 0.25)
    return None


def _created_plan_bbox(plan: ActionPlan) -> tuple[float, float, float, float] | None:
    boxes = [bbox for action in plan.actions if action.kind in CREATE_ACTION_KINDS for bbox in [_action_bbox(action)] if bbox]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _transform_numeric_param(params: dict[str, Any], key: str, *, scale: float, offset: float) -> None:
    if isinstance(params.get(key), (int, float)):
        params[key] = (float(params[key]) * scale) + offset


def _scale_numeric_param(params: dict[str, Any], key: str, scale: float) -> None:
    if isinstance(params.get(key), (int, float)):
        params[key] = float(params[key]) * scale


def _fit_create_actions_to_document(plan: ActionPlan, document: DocumentContext) -> ActionPlan:
    if not document.width or not document.height:
        return plan
    create_actions = [action for action in plan.actions if action.kind in CREATE_ACTION_KINDS]
    if not create_actions:
        return plan
    bbox = _created_plan_bbox(plan)
    if not bbox:
        return plan

    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return plan

    margin = min(12.0, max(4.0, min(float(document.width), float(document.height)) * 0.05))
    available_width = max(1.0, float(document.width) - (margin * 2.0))
    available_height = max(1.0, float(document.height) - (margin * 2.0))
    needs_fit = left < margin or top < margin or right > float(document.width) - margin or bottom > float(document.height) - margin
    if not needs_fit:
        return plan

    scale = min(1.0, available_width / width, available_height / height)
    fitted_width = width * scale
    fitted_height = height * scale
    offset_x = margin + ((available_width - fitted_width) / 2.0) - (left * scale)
    offset_y = margin + ((available_height - fitted_height) / 2.0) - (top * scale)

    fitted_actions: list[Action] = []
    for action in plan.actions:
        params = dict(action.params)
        if action.kind in CREATE_ACTION_KINDS:
            for key in ("x", "cx", "x1", "x2"):
                _transform_numeric_param(params, key, scale=scale, offset=offset_x)
            for key in ("y", "cy", "y1", "y2"):
                _transform_numeric_param(params, key, scale=scale, offset=offset_y)
            for key in ("width", "height", "radius", "inner_radius", "corner_radius", "spacing_x", "spacing_y", "font_size_px", "stroke_width_px"):
                _scale_numeric_param(params, key, scale)
        fitted_actions.append(Action(kind=action.kind, params=params))

    summary = f"{plan.summary} Newly created geometry was fitted inside the current {document.width:g}×{document.height:g}px page."
    return ActionPlan(summary=summary, actions=fitted_actions, needs_confirmation=plan.needs_confirmation)


def _postprocess_plan(prompt: str, plan: ActionPlan, document: DocumentContext) -> ActionPlan:
    return _fit_create_actions_to_document(_guard_document_resize(prompt, plan), document)


def _should_use_layer_schematic_fallback(prompt: str, plan: ActionPlan, image_urls: list[str] | None) -> bool:
    if plan.actions or not image_urls:
        return False
    text = f"{prompt}\n{plan.summary}".lower()
    if not any(word in text for word in ("schematic", "layer", "graphite", "hbn", "substrate", "reference image")):
        return False
    return any(word in text for word in ("recreate", "draw", "build", "make", "create", "approximate", "editable"))


def _prompt_looks_like_publication_figure(prompt: str) -> bool:
    text = prompt.lower()
    return ("publication" in text or "figure" in text) and any(word in text for word in ("plot", "panel", "layout", "trace"))


def _prompt_requests_publication_cleanup(prompt: str) -> bool:
    text = prompt.lower()
    return any(
        phrase in text
        for phrase in (
            "publication ready",
            "publication level",
            "publication quality",
            "make it publishable",
            "make this publishable",
            "polish this figure",
            "clean up this figure",
            "standardize this figure",
        )
    )


def _fallback_visual_plan(prompt: str, document: DocumentContext, reason: str) -> ActionPlan:
    if _prompt_looks_like_publication_figure(prompt):
        return build_publication_figure_plan(
            document,
            summary=f"{reason} The agent generated a simplified editable publication-figure fallback instead.",
        )
    return build_layer_schematic_plan(
        document,
        summary=f"{reason} The agent generated an editable layer-schematic fallback instead.",
    )


def _postprocess_remote_plan(
    prompt: str,
    plan: ActionPlan,
    document: DocumentContext,
    image_urls: list[str] | None,
) -> ActionPlan:
    processed = _postprocess_plan(prompt, plan, document)
    if _prompt_requests_publication_cleanup(prompt) and not processed.actions:
        safe_actions = safe_publication_actions(document)
        if safe_actions:
            return _postprocess_plan(
                prompt,
                ActionPlan(
                    summary="Applied safe publication-rubric fixes from current QA findings.",
                    actions=safe_actions,
                    needs_confirmation=False,
                ),
                document,
            )
    if _should_use_layer_schematic_fallback(prompt, processed, image_urls):
        return _postprocess_plan(
            prompt,
            _fallback_visual_plan(
                prompt,
                document,
                "The remote planner described a supported visual target but returned no executable actions.",
            ),
            document,
        )
    return processed


def _request_url(base_url: str | None = None, provider: str = DEFAULT_PROVIDER) -> str:
    _load_local_env()
    if provider == "deepseek":
        candidate = base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL
        return _normalize_deepseek_url(candidate)
    return base_url or os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)


def _normalize_deepseek_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _model_name(model: str | None, provider: str) -> str:
    _load_local_env()
    return os.environ.get("MAIN_MODEL", DEFAULT_MODEL)


def _request_headers(resolved_api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }


def _api_timeout_seconds() -> float:
    _load_local_env()
    value = os.environ.get("INKSCAPE_COPILOT_API_TIMEOUT_SECONDS")
    try:
        return max(30.0, float(value)) if value else 180.0
    except ValueError:
        return 180.0


def _image_detail() -> str:
    _load_local_env()
    value = (os.environ.get("INKSCAPE_COPILOT_IMAGE_DETAIL") or "low").strip().lower()
    return value if value in {"low", "high", "auto"} else "low"


def _system_prompt() -> str:
    return (
        "You are FigureAgent for Inkscape, an AI planner for publication-quality figure editing. "
        "Return only actions supported by the application. "
        "Selection-based actions operate on the current selection. "
        "Creation actions may create new basic shapes on the current layer. "
        "The document_context.objects array is a compact scene graph snapshot of existing SVG objects; it may include role, panel, axis, parent_id, group_id, descendant_count, panel_root_id, label_for, attached_to, text_group_id, and glyph_for hints for semantic targeting. "
        "The document_context.panels array lists detected figure panels such as a, b, c, d, e, f, or g with label objects, bounding boxes, and object counts; use it for panel-specific edits instead of assuming only a-d exist. "
        "Use object_id, object_index, visible text, or semantic selectors like role, panel, axis, tag, parent_id, group_id, panel_root_id, label_for, attached_to, text_group_id, and glyph_for from that snapshot for direct edits. "
        "When modifying an existing design, prefer object-targeted actions like select_targets, set_object_fill_color, set_object_fill_none, set_object_stroke_color, set_object_stroke_none, set_object_stroke_width, set_object_dash_pattern, set_object_font_size, set_object_font_weight, move_object, replace_text, and delete_object instead of recreating the design. "
        "Use relationships when available: label_for links labels to their bars, attached_to links connectors or electrodes to target layers, panel_root_id links objects to stable figure roots, and text_group_id/glyph_for link path-based Greek/math glyphs such as rho or Omega to nearby text labels. "
        "If the user refers to figure parts like ticks, axis labels, panel a, connectors, electrodes, layer labels, or x-axis, first target matching objects with select_targets using semantic selectors. "
        "If the user refers to the whole schematic, the whole figure, or figure a/b/c, first build a multi-selection with select_targets using the panel selector and include_descendants=true, then use selection transforms like set_selection_position, scale_selection, align_selection, or distribute_selection. "
        "When the user requests font sizes in points, convert to CSS/SVG pixels with font_size_px = pt * 4 / 3; the executor compensates for parent transforms so the visual rendered size matches the requested point size. "
        "If the user explicitly says they already selected objects in Inkscape, you may use selection-based actions even when document_context.selection_count is 0, because the snapshot can lag behind the live selection. "
        "Use set_tick_length for requests about making ticks longer or shorter, set_tick_thickness for tick stroke weight, and set_tick_label_size for numeric tick label text size. "
        "For publication plot resizing, prefer resize_plot_width or resize_plot_height over scale_selection. These semantic resize actions anchor on detected axis lines when possible, change the plot geometry, keep tick length, tick thickness, stroke widths, and text sizes visually stable, and avoid scaling panel labels. Use scale_selection only when the user explicitly wants every selected object scaled visually. "
        "Use set_object_font_family, set_object_font_weight, set_object_font_style, and set_object_text_anchor for typography polish; use set_object_stroke_linecap, set_object_stroke_linejoin, and set_object_arrowhead for line/arrow styling. "
        "For publication-ready or publication-level cleanup requests, use publication_rubric, publication_qa, and publication_fix_suggestions from the user prompt. Apply safe obvious fixes such as panel labels 12 pt, axis labels 10 pt, tick labels 9 pt, and consistent tick styles; avoid ambiguous fixes like renaming missing/duplicate panels unless the user explicitly requests it. "
        "After duplicate_selection or create_* actions, later actions in the same plan should assume the newly created object(s) are the active target. "
        "For diagrams, approximate complex visual references with supported primitives and prefer high-level diagram actions like "
        "create_layer_bar, create_rounded_rectangle, create_repeated_circles, create_arrow, create_bracket, and create_line. "
        "When a user asks to proceed, continue from the provided working brief instead of asking for the target again. "
        "If the user approves a suggested cleanup or says an action is okay, choose sensible defaults and return executable actions. "
        "Only use set_document_size when the user explicitly asks to change the page, canvas, document, artboard, or sheet size. "
        "Do not resize the page just because the user asks to create or fit objects. "
        "Use ASCII-safe scientific labels such as SiO2/Si instead of Unicode subscripts. "
        "Every create_layer_bar action must include a non-empty params.text label; use layer if no specific label is known. "
        "For rectangle cleanup, prefer a polished dark fill, no visible stroke, and a moderate size adjustment only if size is requested or implied. "
        "If the request would require boolean geometry operations, arbitrary path editing, or any unsupported behavior, "
        "return an empty actions list with needs_confirmation=true and explain the limitation in summary. "
        "Prefer small, precise plans. "
        "Supported action kinds are: "
        "set_fill_color, set_fill_none, set_stroke_color, set_stroke_none, set_stroke_width, set_font_size, set_corner_radius, set_dash_pattern, "
        "set_tick_length, set_tick_thickness, set_tick_label_size, "
        "set_z_order, set_document_size, set_opacity, move_selection, set_selection_position, align_selection, distribute_selection, duplicate_selection, "
        "resize_selection, resize_plot_width, resize_plot_height, scale_selection, rotate_selection, rename_selection, select_object, select_targets, delete_object, move_object, set_object_position, set_object_size, "
        "set_object_fill_color, set_object_fill_none, set_object_stroke_color, set_object_stroke_none, set_object_stroke_width, set_object_stroke_linecap, set_object_stroke_linejoin, set_object_arrowhead, set_object_dash_pattern, "
        "set_object_font_size, set_object_font_family, set_object_font_weight, set_object_font_style, set_object_text_anchor, replace_text, "
        "create_rectangle, create_rounded_rectangle, "
        "create_circle, create_ellipse, create_polygon, create_star, create_repeated_circles, create_line, create_arrow, create_bracket, create_layer_bar, create_text."
    )


def _chat_system_prompt() -> str:
    return (
        "You are FigureAgent for Inkscape, an interactive AI figure-editing agent. "
        "Reply concisely and operationally. "
        "Keep replies to 1 to 4 short lines. "
        "Focus on what you are about to change, create, or target in the drawing. "
        "Prefer a compact format like: intent, then next actions. "
        "Do not give long explanations, tutorials, or design commentary unless the user explicitly asks for them. "
        "If the extension cannot do part of the request, say that briefly and state the closest supported step."
    )


def _user_prompt(prompt: str, document: DocumentContext) -> str:
    qa = publication_qa(document)
    return json.dumps(
        {
            "user_prompt": prompt,
            "document_context": document.to_dict(),
            "publication_rubric": PUBLICATION_RUBRIC_SUMMARY,
            "publication_qa": qa,
            "publication_fix_suggestions": publication_fix_suggestions(document, qa),
            "publication_memory": publication_memory_summary(),
            "action_param_rules": {
                "set_fill_color": {"params": {"hex": "#RRGGBB"}},
                "set_fill_none": {"params": {}},
                "set_stroke_color": {"params": {"hex": "#RRGGBB"}},
                "set_stroke_none": {"params": {}},
                "set_stroke_width": {"params": {"stroke_width_px": 2.0}},
                "set_font_size": {"params": {"font_size_px": 24.0}},
                "set_corner_radius": {"params": {"corner_radius": 4.0}},
                "set_dash_pattern": {"params": {"dash_pattern": "2,2"}},
                "set_z_order": {"params": {"text": "front"}},
                "set_document_size": {"params": {"width": 100.0, "height": 50.0}},
                "set_opacity": {"params": {"opacity_percent": 85.0}},
                "set_tick_length": {"params": {"role": "axis_tick", "panel": "a", "axis": "x", "length_px": 8.0}},
                "set_tick_thickness": {"params": {"role": "axis_tick", "panel": "a", "axis": "x", "stroke_width_px": 2.0}},
                "set_tick_label_size": {"params": {"role": "tick_label", "panel": "a", "axis": "x", "font_size_px": 10.0}},
                "move_selection": {"params": {"delta_x_px": 0.0, "delta_y_px": 0.0}},
                "set_selection_position": {"params": {"x": 24.0, "y": 40.0}},
                "align_selection": {"params": {"text": "left"}},
                "distribute_selection": {"params": {"text": "horizontal"}},
                "duplicate_selection": {"params": {"count": 1, "delta_x_px": 80.0, "delta_y_px": 0.0}},
                "resize_selection": {"params": {"width": 120.0, "height": 80.0}},
                "resize_plot_width": {"params": {"object_id": None, "text": None, "role": None, "panel": "c", "axis": None, "percent": 50.0, "width": None}},
                "resize_plot_height": {"params": {"object_id": None, "text": None, "role": None, "panel": "c", "axis": None, "percent": 80.0, "height": None}},
                "scale_selection": {"params": {"percent": 100.0}},
                "rotate_selection": {"params": {"degrees": 15.0}},
                "rename_selection": {"params": {"prefix": "badge"}},
                "select_object": {"params": {"object_id": "rect123", "object_index": None, "text": None, "role": None, "panel": None, "axis": None, "tag": None, "parent_id": None, "group_id": None, "panel_root_id": None, "label_for": None, "attached_to": None, "text_group_id": None, "glyph_for": None, "include_descendants": None}},
                "select_targets": {"params": {"object_id": None, "object_index": None, "text": None, "role": "layer_bar", "panel": "a", "axis": None, "tag": None, "parent_id": None, "group_id": None, "panel_root_id": None, "label_for": None, "attached_to": None, "text_group_id": None, "glyph_for": None, "include_descendants": False}},
                "select_text_group_example": {"params": {"object_id": None, "object_index": None, "text": None, "role": None, "panel": "c", "axis": None, "tag": None, "parent_id": None, "group_id": None, "panel_root_id": None, "label_for": None, "attached_to": None, "text_group_id": "text123", "glyph_for": None, "include_descendants": False}},
                "select_panel_objects_example": {"params": {"object_id": None, "object_index": None, "text": None, "role": None, "panel": "a", "axis": None, "tag": None, "parent_id": None, "group_id": None, "panel_root_id": "panel-a-root", "label_for": None, "attached_to": None, "text_group_id": None, "glyph_for": None, "include_descendants": True}},
                "delete_object": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None}},
                "move_object": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None, "delta_x_px": 12.0, "delta_y_px": 0.0}},
                "set_object_position": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None, "x": 40.0, "y": 60.0}},
                "set_object_size": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None, "width": 120.0, "height": 40.0}},
                "set_object_fill_color": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None, "hex": "#2563eb"}},
                "set_object_fill_none": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None}},
                "set_object_stroke_color": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None, "hex": "#111827"}},
                "set_object_stroke_none": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None}},
                "set_object_stroke_width": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None, "stroke_width_px": 2.0}},
                "set_object_stroke_linecap": {"params": {"object_id": None, "text": None, "role": "axis_line", "panel": None, "axis": None, "stroke_linecap": "round"}},
                "set_object_stroke_linejoin": {"params": {"object_id": None, "text": None, "role": "plot_curve", "panel": None, "axis": None, "stroke_linejoin": "round"}},
                "set_object_arrowhead": {"params": {"object_id": None, "text": None, "role": "connector", "panel": None, "axis": None, "marker": "end"}},
                "set_object_dash_pattern": {"params": {"object_id": "rect123", "text": None, "role": None, "panel": None, "axis": None, "dash_pattern": "4,2"}},
                "set_object_font_size": {"params": {"object_id": "text123", "text": None, "role": None, "panel": None, "axis": None, "font_size_px": 12.0}},
                "set_object_font_family": {"params": {"object_id": "text123", "text": None, "role": None, "panel": None, "axis": None, "font_family": "Arial"}},
                "set_object_font_weight": {"params": {"object_id": None, "text": None, "role": "panel_label", "panel": None, "axis": None, "font_weight": "bold"}},
                "set_object_font_style": {"params": {"object_id": "text123", "text": None, "role": None, "panel": None, "axis": None, "font_style": "italic"}},
                "set_object_text_anchor": {"params": {"object_id": None, "text": None, "role": "axis_label", "panel": None, "axis": "x", "text_anchor": "middle"}},
                "replace_text": {"params": {"object_id": "text123", "text": None, "role": None, "panel": None, "axis": None, "new_text": "new label"}},
                "create_rectangle": {
                    "params": {
                        "x": 100.0,
                        "y": 100.0,
                        "width": 120.0,
                        "height": 120.0,
                        "fill_hex": "#2563eb",
                        "stroke_hex": None,
                        "stroke_width_px": None,
                        "dash_pattern": None,
                        "corner_radius": None,
                        "text": None,
                        "text_hex": None,
                        "spacing_x": None,
                        "spacing_y": None,
                        "x1": None,
                        "x2": None,
                        "y1": None,
                        "y2": None,
                    }
                },
                "create_rounded_rectangle": {
                    "params": {
                        "x": 18.0,
                        "y": 15.0,
                        "width": 184.0,
                        "height": 86.0,
                        "corner_radius": 5.0,
                        "fill_hex": None,
                        "stroke_hex": "#111827",
                        "stroke_width_px": 1.2,
                        "dash_pattern": "2,2",
                    }
                },
                "create_circle": {
                    "params": {
                        "cx": 200.0,
                        "cy": 200.0,
                        "radius": 60.0,
                        "fill_hex": "#2563eb",
                        "stroke_hex": None,
                        "stroke_width_px": None,
                    }
                },
                "create_ellipse": {
                    "params": {
                        "cx": 200.0,
                        "cy": 200.0,
                        "width": 120.0,
                        "height": 80.0,
                        "fill_hex": "#2563eb",
                        "stroke_hex": None,
                        "stroke_width_px": None,
                    }
                },
                "create_repeated_circles": {
                    "params": {
                        "x": 78.0,
                        "y": 52.0,
                        "radius": 2.2,
                        "count": 9,
                        "spacing_x": 8.0,
                        "spacing_y": 0.0,
                        "fill_hex": "#111827",
                        "stroke_hex": None,
                        "stroke_width_px": None,
                    }
                },
                "create_polygon": {
                    "params": {
                        "cx": 120.0,
                        "cy": 120.0,
                        "radius": 40.0,
                        "count": 6,
                        "degrees": 0.0,
                        "fill_hex": "#2563eb",
                        "stroke_hex": None,
                        "stroke_width_px": None,
                    }
                },
                "create_star": {
                    "params": {
                        "cx": 120.0,
                        "cy": 120.0,
                        "radius": 40.0,
                        "inner_radius": 18.0,
                        "count": 5,
                        "degrees": 0.0,
                        "fill_hex": "#f59e0b",
                        "stroke_hex": None,
                        "stroke_width_px": None,
                    }
                },
                "create_line": {
                    "params": {
                        "x1": 30.0,
                        "y1": 60.0,
                        "x2": 190.0,
                        "y2": 60.0,
                        "stroke_hex": "#111827",
                        "stroke_width_px": 2.0,
                        "dash_pattern": None,
                    }
                },
                "create_arrow": {
                    "params": {
                        "x1": 34.0,
                        "y1": 92.0,
                        "x2": 62.0,
                        "y2": 92.0,
                        "stroke_hex": "#dc2626",
                        "stroke_width_px": 3.0,
                    }
                },
                "create_bracket": {
                    "params": {
                        "x": 42.0,
                        "y1": 50.0,
                        "y2": 82.0,
                        "width": 8.0,
                        "stroke_hex": "#111827",
                        "stroke_width_px": 1.5,
                    }
                },
                "create_layer_bar": {
                    "params": {
                        "x": 76.0,
                        "y": 24.0,
                        "width": 88.0,
                        "height": 10.0,
                        "corner_radius": 2.0,
                        "text": "graphite",
                        "font_size_px": 8.0,
                        "fill_hex": "#8a8a8a",
                        "stroke_hex": None,
                        "stroke_width_px": None,
                        "text_hex": "#111827",
                    }
                },
                "create_text": {
                    "params": {
                        "text": "Hello world",
                        "x": 24.0,
                        "y": 40.0,
                        "font_size_px": 24.0,
                        "fill_hex": "#111827",
                    }
                },
            },
        },
        indent=2,
    )


def _prompt_with_working_brief(prompt: str, working_brief: str | None) -> str:
    if not working_brief:
        return prompt
    return (
        f"{prompt}\n\n"
        "Relevant working brief from the current conversation:\n"
        f"{working_brief}\n\n"
        "Use this brief as the design target for follow-up approvals or instructions."
    )


def _image_content_items(image_urls: list[str] | None) -> list[dict[str, Any]]:
    return [
        {"type": "input_image", "image_url": image_url, "detail": _image_detail()}
        for image_url in image_urls or []
        if isinstance(image_url, str) and image_url.startswith("data:image/")
    ]


def _user_content_with_images(text: str, image_urls: list[str] | None) -> list[dict[str, Any]]:
    return [{"type": "input_text", "text": text}, *_image_content_items(image_urls)]


def _chat_messages(messages: list[dict[str, Any]], document: DocumentContext) -> list[dict[str, Any]]:
    qa = publication_qa(document)
    context_block = json.dumps(
        {
            "document_context": document.to_dict(),
            "publication_rubric": PUBLICATION_RUBRIC_SUMMARY,
            "publication_qa": qa,
            "publication_fix_suggestions": publication_fix_suggestions(document, qa),
            "publication_memory": publication_memory_summary(),
            "note": "This context describes the current Inkscape document state FigureAgent can act on.",
        },
        indent=2,
    )
    return [{"role": "system", "content": _chat_system_prompt()}, {"role": "system", "content": context_block}, *messages]


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    image_count = 0
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"input_text", "text"} and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif item_type in {"input_image", "image_url"}:
            image_count += 1
    if image_count:
        parts.append(f"[{image_count} attached image(s) omitted in DeepSeek text-only mode.]")
    return "\n".join(part for part in parts if part).strip()


def _chat_completion_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        if role not in {"system", "user", "assistant"}:
            continue
        text = _content_to_text(message.get("content", ""))
        if text:
            converted.append({"role": role, "content": text})
    return converted


def _deepseek_chat_completion(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    response_format: dict[str, str] | None = None,
) -> str:
    request_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if response_format:
        request_payload["response_format"] = response_format

    request = urllib.request.Request(
        _request_url(base_url, "deepseek"),
        data=json.dumps(request_payload).encode("utf-8"),
        headers=_request_headers(api_key),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_api_timeout_seconds(), context=_ssl_context()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAIPlannerError(f"DeepSeek API returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        cafile = _resolve_ca_bundle()
        if cafile:
            raise OpenAIPlannerError(f"Could not reach DeepSeek API using CA bundle {cafile}: {exc.reason}") from exc
        raise OpenAIPlannerError(f"Could not reach DeepSeek API: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OpenAIPlannerError(f"DeepSeek API timed out after {_api_timeout_seconds():g} seconds.") from exc

    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise OpenAIPlannerError(f"DeepSeek API returned an unexpected payload: {_json_error_snippet(raw)}") from exc
    if not isinstance(content, str) or not content.strip():
        raise OpenAIPlannerError("DeepSeek API returned an empty message.")
    return content.strip()


def _stream_deepseek_chat_completion(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
) -> Iterator[str]:
    request_payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    request = urllib.request.Request(
        _request_url(base_url, "deepseek"),
        data=json.dumps(request_payload).encode("utf-8"),
        headers=_request_headers(api_key),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_api_timeout_seconds(), context=_ssl_context()) as response:
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload_text = line[len("data:") :].strip()
                if payload_text == "[DONE]":
                    break
                try:
                    event_payload = json.loads(payload_text)
                    delta = event_payload["choices"][0].get("delta", {}).get("content")
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    continue
                if isinstance(delta, str) and delta:
                    yield delta
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAIPlannerError(f"DeepSeek API returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        cafile = _resolve_ca_bundle()
        if cafile:
            raise OpenAIPlannerError(f"Could not reach DeepSeek API using CA bundle {cafile}: {exc.reason}") from exc
        raise OpenAIPlannerError(f"Could not reach DeepSeek API: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OpenAIPlannerError(f"DeepSeek API timed out after {_api_timeout_seconds():g} seconds.") from exc


def stream_chat_reply(
    messages: list[dict[str, Any]],
    document: DocumentContext,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> Iterator[str]:
    provider = _provider()
    resolved_api_key = _resolve_api_key(api_key, provider)
    if not resolved_api_key:
        key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
        raise OpenAIPlannerError(f"{key_name} is not set.")

    if provider == "deepseek":
        yield from _stream_deepseek_chat_completion(
            _chat_completion_messages(_chat_messages(messages, document)),
            api_key=resolved_api_key,
            model=_model_name(model, provider),
            base_url=base_url,
        )
        return

    request_payload = {
        "model": _model_name(model, provider),
        "input": _chat_messages(messages, document),
        "stream": True,
    }

    request = urllib.request.Request(
        _request_url(base_url, provider),
        data=json.dumps(request_payload).encode("utf-8"),
        headers=_request_headers(resolved_api_key),
        method="POST",
    )

    event_name: str | None = None
    data_lines: list[str] = []

    try:
        with urllib.request.urlopen(request, timeout=_api_timeout_seconds(), context=_ssl_context()) as response:
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    if not data_lines:
                        event_name = None
                        continue

                    payload_text = "\n".join(data_lines)
                    data_lines = []

                    if payload_text == "[DONE]":
                        break

                    try:
                        event_payload = json.loads(payload_text)
                    except json.JSONDecodeError:
                        event_name = None
                        continue

                    current_event = event_name or event_payload.get("type")
                    event_name = None

                    if current_event == "response.output_text.delta":
                        delta = event_payload.get("delta")
                        if isinstance(delta, str):
                            yield delta
                    elif current_event == "error":
                        raise OpenAIPlannerError(f"Streaming API error: {payload_text}")

                    continue

                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                    continue

                if line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAIPlannerError(f"OpenAI API returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        cafile = _resolve_ca_bundle()
        if cafile:
            raise OpenAIPlannerError(f"Could not reach OpenAI API using CA bundle {cafile}: {exc.reason}") from exc
        raise OpenAIPlannerError(f"Could not reach OpenAI API: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        if image_urls:
            return _postprocess_plan(
                prompt,
                _fallback_visual_plan(
                    prompt,
                    document,
                    f"OpenAI image planning timed out after {_api_timeout_seconds():g} seconds.",
                ),
                document,
            )
        raise OpenAIPlannerError(f"OpenAI API timed out after {_api_timeout_seconds():g} seconds.") from exc


def plan_with_openai(
    prompt: str,
    document: DocumentContext,
    *,
    image_urls: list[str] | None = None,
    working_brief: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> ActionPlan:
    provider = _provider()
    resolved_api_key = _resolve_api_key(api_key, provider)
    if not resolved_api_key:
        key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
        raise OpenAIPlannerError(f"{key_name} is not set.")

    if provider == "deepseek":
        plan_prompt = _user_prompt(_prompt_with_working_brief(prompt, working_brief), document)
        allowed_kinds = ", ".join(sorted(action_plan_json_schema()["properties"]["actions"]["items"]["properties"]["kind"]["enum"]))
        messages = [
            {
                "role": "system",
                "content": (
                    f"{_system_prompt()} Return only a valid JSON object. "
                    "The JSON object must have summary, actions, and needs_confirmation fields. "
                    f"Every action.kind must be one of: {allowed_kinds}. Never use null for action.kind."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate a JSON action plan for this Inkscape request. "
                    "Do not include markdown fences or commentary outside JSON.\n\n"
                    f"{plan_prompt}"
                ),
            },
        ]
        if image_urls:
            messages[-1]["content"] += (
                f"\n\nNote: {len(image_urls)} attached image(s) are not sent to the DeepSeek planner. "
                "Use the conversation working brief and user text as the design target."
            )

        last_error: Exception | None = None
        output_text = ""
        for attempt in range(2):
            if attempt:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"The previous JSON failed validation with this error: {last_error}. "
                            "Return corrected JSON only. Do not add markdown. "
                            "Use only supported action kinds and required numeric params."
                        ),
                    }
                )
            output_text = _deepseek_chat_completion(
                messages,
                api_key=resolved_api_key,
                model=_model_name(model, provider),
                base_url=base_url,
                response_format={"type": "json_object"},
            )
            try:
                plan_payload = json.loads(output_text)
                return _postprocess_remote_plan(prompt, ActionPlan.from_dict(plan_payload), document, image_urls)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc

        snippet = _json_error_snippet(output_text)
        if isinstance(last_error, json.JSONDecodeError):
            raise OpenAIPlannerError(f"DeepSeek API did not return valid JSON for the action plan. Output began: {snippet}") from last_error
        raise OpenAIPlannerError(f"DeepSeek plan failed validation after retry: {last_error}. Output began: {snippet}") from last_error

    request_payload = {
        "model": _model_name(model, provider),
        "input": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": _user_content_with_images(
                    _user_prompt(_prompt_with_working_brief(prompt, working_brief), document),
                    image_urls,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "inkscape_action_plan",
                "strict": True,
                "schema": action_plan_json_schema(),
            }
        },
    }

    request = urllib.request.Request(
        _request_url(base_url, provider),
        data=json.dumps(request_payload).encode("utf-8"),
        headers=_request_headers(resolved_api_key),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_api_timeout_seconds(), context=_ssl_context()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAIPlannerError(f"OpenAI API returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        cafile = _resolve_ca_bundle()
        if cafile:
            raise OpenAIPlannerError(f"Could not reach OpenAI API using CA bundle {cafile}: {exc.reason}") from exc
        raise OpenAIPlannerError(f"Could not reach OpenAI API: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OpenAIPlannerError(f"OpenAI API timed out after {_api_timeout_seconds():g} seconds.") from exc

    try:
        payload = json.loads(raw)
        output_text = _extract_output_text(payload)
        plan_payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        snippet = _json_error_snippet(output_text if "output_text" in locals() else raw)
        raise OpenAIPlannerError(f"OpenAI API did not return valid JSON for the action plan. Output began: {snippet}") from exc

    try:
        return _postprocess_remote_plan(prompt, ActionPlan.from_dict(plan_payload), document, image_urls)
    except ValueError as exc:
        raise OpenAIPlannerError(f"OpenAI plan failed validation: {exc}") from exc
