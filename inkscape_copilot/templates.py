from __future__ import annotations

from .planner import DocumentContext
from .schema import Action, ActionPlan


def _page_size(document: DocumentContext) -> tuple[float, float]:
    return float(document.width or 220.0), float(document.height or 290.0)


def build_layer_schematic_plan(document: DocumentContext, *, summary: str | None = None) -> ActionPlan:
    page_width, page_height = _page_size(document)
    margin = max(8.0, min(page_width, page_height) * 0.05)
    frame_width = min(page_width - (2.0 * margin), 190.0)
    frame_height = min(page_height - (2.0 * margin), 96.0)
    frame_x = (page_width - frame_width) / 2.0
    frame_y = margin
    stack_width = frame_width * 0.48
    stack_x = frame_x + (frame_width * 0.33)
    layer_h = frame_height * 0.105
    dot_r = max(1.2, frame_width * 0.009)
    font = max(5.5, frame_height * 0.075)

    def params(**kwargs):
        base = {
            "count": None,
            "corner_radius": None,
            "cx": None,
            "cy": None,
            "dash_pattern": None,
            "degrees": None,
            "hex": None,
            "delta_x_px": None,
            "delta_y_px": None,
            "fill_hex": None,
            "font_size_px": None,
            "group_id": None,
            "panel_root_id": None,
            "label_for": None,
            "attached_to": None,
            "height": None,
            "include_descendants": None,
            "inner_radius": None,
            "length_px": None,
            "opacity_percent": None,
            "object_id": None,
            "object_index": None,
            "axis": None,
            "panel": "a",
            "parent_id": None,
            "percent": None,
            "prefix": None,
            "radius": None,
            "new_text": None,
            "role": None,
            "stroke_hex": None,
            "stroke_width_px": None,
            "tag": None,
            "text": None,
            "text_hex": None,
            "width": None,
            "x": None,
            "x1": None,
            "x2": None,
            "y": None,
            "y1": None,
            "y2": None,
            "spacing_x": None,
            "spacing_y": None,
        }
        base.update(kwargs)
        return base

    y0 = frame_y + frame_height * 0.11
    y_gap = frame_height * 0.16
    substrate_y = frame_y + frame_height * 0.80
    actions = [
        Action(
            "create_rounded_rectangle",
            params(
                x=frame_x,
                y=frame_y,
                width=frame_width,
                height=frame_height,
                corner_radius=5.0,
                fill_hex="#ffffff",
                stroke_hex="#111827",
                stroke_width_px=1.2,
                dash_pattern="2,2",
            ),
        ),
        Action("create_text", params(text="a", x=max(2.0, frame_x - 13.0), y=frame_y + 8.0, font_size_px=10.0, fill_hex="#111827")),
        Action("create_layer_bar", params(x=stack_x, y=y0, width=stack_width, height=layer_h, corner_radius=2.0, text="graphite", font_size_px=font, fill_hex="#8a8a8a", text_hex="#111827")),
        Action("create_layer_bar", params(x=stack_x, y=y0 + y_gap, width=stack_width, height=layer_h, corner_radius=2.0, text="hBN", font_size_px=font, fill_hex="#7ec8ee", text_hex="#111827")),
        Action("create_repeated_circles", params(x=stack_x + dot_r, y=y0 + y_gap * 2.25, radius=dot_r, count=10, spacing_x=(stack_width - dot_r * 2.0) / 9.0, spacing_y=0.0, fill_hex="#222222")),
        Action("create_repeated_circles", params(x=stack_x + dot_r + ((stack_width - dot_r * 2.0) / 18.0), y=y0 + y_gap * 2.85, radius=dot_r, count=9, spacing_x=(stack_width - dot_r * 2.0) / 9.0, spacing_y=0.0, fill_hex="#222222")),
        Action("create_layer_bar", params(x=stack_x, y=y0 + y_gap * 3.55, width=stack_width, height=layer_h, corner_radius=2.0, text="hBN", font_size_px=font, fill_hex="#7ec8ee", text_hex="#111827")),
        Action("create_layer_bar", params(x=stack_x, y=y0 + y_gap * 4.75, width=stack_width, height=layer_h, corner_radius=2.0, text="graphite", font_size_px=font, fill_hex="#8a8a8a", text_hex="#111827")),
        Action("create_layer_bar", params(x=frame_x + frame_width * 0.23, y=substrate_y, width=frame_width * 0.54, height=layer_h, corner_radius=0.0, text="SiO2/Si", font_size_px=font, fill_hex="#8b5f8f", text_hex="#111827")),
    ]

    contact_x = frame_x + frame_width * 0.20
    for x_offset, top_mul, bottom_mul in ((0.0, 0.22, 0.66), (frame_width * 0.07, 0.10, 0.55), (frame_width * 0.14, 0.32, 0.76)):
        x = contact_x + x_offset
        actions.append(Action("create_line", params(x1=x, y1=frame_y + frame_height * top_mul, x2=x, y2=frame_y + frame_height * bottom_mul, stroke_hex="#4b5563", stroke_width_px=1.4)))
        actions.append(Action("create_line", params(x1=x - 6.0, y1=frame_y + frame_height * top_mul, x2=x + 6.0, y2=frame_y + frame_height * top_mul, stroke_hex="#4b5563", stroke_width_px=1.4)))
        actions.append(Action("create_line", params(x1=x - 6.0, y1=frame_y + frame_height * bottom_mul, x2=x + 6.0, y2=frame_y + frame_height * bottom_mul, stroke_hex="#4b5563", stroke_width_px=1.4)))

    arrow_y = substrate_y + layer_h * 0.55
    actions.extend(
        [
            Action("create_arrow", params(x1=frame_x + 18.0, y1=arrow_y, x2=frame_x + 44.0, y2=arrow_y, stroke_hex="#dc2626", stroke_width_px=3.0)),
            Action("create_arrow", params(x1=frame_x + frame_width - 18.0, y1=arrow_y, x2=frame_x + frame_width - 44.0, y2=arrow_y, stroke_hex="#2563eb", stroke_width_px=3.0)),
        ]
    )

    return ActionPlan(
        summary=summary
        or "Built a clean editable layer schematic fallback from the attached reference image.",
        actions=actions,
        needs_confirmation=False,
    )


def build_publication_figure_plan(document: DocumentContext, *, summary: str | None = None) -> ActionPlan:
    page_width, page_height = _page_size(document)
    actions = list(build_layer_schematic_plan(document).actions)

    def params(**kwargs):
        base = {
            "count": None,
            "corner_radius": None,
            "cx": None,
            "cy": None,
            "dash_pattern": None,
            "degrees": None,
            "hex": None,
            "delta_x_px": None,
            "delta_y_px": None,
            "fill_hex": None,
            "font_size_px": None,
            "group_id": None,
            "panel_root_id": None,
            "label_for": None,
            "attached_to": None,
            "height": None,
            "include_descendants": None,
            "inner_radius": None,
            "length_px": None,
            "opacity_percent": None,
            "object_id": None,
            "object_index": None,
            "axis": None,
            "panel": None,
            "parent_id": None,
            "percent": None,
            "prefix": None,
            "radius": None,
            "new_text": None,
            "role": None,
            "stroke_hex": None,
            "stroke_width_px": None,
            "tag": None,
            "text": None,
            "text_hex": None,
            "width": None,
            "x": None,
            "x1": None,
            "x2": None,
            "y": None,
            "y1": None,
            "y2": None,
            "spacing_x": None,
            "spacing_y": None,
        }
        base.update(kwargs)
        return base

    plot_x = page_width * 0.13
    plot_w = page_width * 0.76
    plot_h = page_height * 0.18
    plot_ys = (page_height * 0.52, page_height * 0.74)
    for panel, y, label, color_a, color_b in (
        ("b", plot_ys[0], "resistance vs density", "#dc2626", "#2563eb"),
        ("c", plot_ys[1], "transport trace", "#dc2626", "#2563eb"),
    ):
        left = plot_x
        top = y
        right = plot_x + plot_w
        bottom = y + plot_h
        actions.append(Action("create_text", params(panel=panel, text=panel, x=left - 16.0, y=top + 4.0, font_size_px=8.0, fill_hex="#111827")))
        actions.append(Action("create_line", params(panel=panel, role="axis_line", axis="x", x1=left, y1=bottom, x2=right, y2=bottom, stroke_hex="#555555", stroke_width_px=1.0)))
        actions.append(Action("create_line", params(panel=panel, role="axis_line", axis="y", x1=left, y1=top, x2=left, y2=bottom, stroke_hex="#555555", stroke_width_px=1.0)))
        actions.append(Action("create_text", params(panel=panel, text=label, x=left + plot_w * 0.35, y=top + 8.0, font_size_px=5.5, fill_hex="#555555")))
        for i in range(1, 5):
            tx = left + (plot_w * i / 5.0)
            ty = bottom - (plot_h * i / 5.0)
            actions.append(Action("create_line", params(panel=panel, role="axis_tick", axis="x", x1=tx, y1=bottom, x2=tx, y2=bottom + 3.0, stroke_hex="#555555", stroke_width_px=0.8)))
            actions.append(Action("create_line", params(panel=panel, role="axis_tick", axis="y", x1=left - 3.0, y1=ty, x2=left, y2=ty, stroke_hex="#555555", stroke_width_px=0.8)))
        previous_a = None
        previous_b = None
        for i in range(9):
            t = i / 8.0
            x = left + plot_w * t
            curve_a = bottom - plot_h * (0.18 + 0.7 * (t**2) + (0.12 if i in {4, 5} and panel == "c" else 0.0))
            curve_b = bottom - plot_h * (0.14 + 0.63 * (t**2) + (0.08 if i in {4, 5} and panel == "c" else 0.0))
            current_a = (x, curve_a)
            current_b = (x, curve_b)
            if previous_a:
                actions.append(Action("create_line", params(panel=panel, role="plot_curve", x1=previous_a[0], y1=previous_a[1], x2=current_a[0], y2=current_a[1], stroke_hex=color_a, stroke_width_px=1.1)))
            if previous_b:
                actions.append(Action("create_line", params(panel=panel, role="plot_curve", x1=previous_b[0], y1=previous_b[1], x2=current_b[0], y2=current_b[1], stroke_hex=color_b, stroke_width_px=1.1)))
            previous_a = current_a
            previous_b = current_b

    return ActionPlan(
        summary=summary
        or "Built a simplified editable publication-figure fallback with a layer schematic and two plot panels.",
        actions=actions,
        needs_confirmation=False,
    )
