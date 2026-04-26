from inkscape_copilot.planner import DocumentContext, DocumentObject, PanelInfo
from inkscape_copilot.publication_fixes import safe_publication_actions
from inkscape_copilot.publication_qa import publication_qa


def _tick(object_id: str, *, axis: str, length: float, stroke_width: float) -> DocumentObject:
    return DocumentObject(
        object_id=object_id,
        tag="line",
        text=None,
        fill=None,
        stroke="#000000",
        bbox={"left": 0.0, "top": 0.0, "width": 0.0 if axis == "x" else length, "height": length if axis == "x" else 0.0},
        stroke_width=f"{stroke_width}px",
        role="axis_tick",
        axis=axis,
        line_points={"x1": 0.0, "y1": 0.0, "x2": 0.0 if axis == "x" else length, "y2": length if axis == "x" else 0.0},
    )


def test_axis_tick_qa_prefers_axis_specific_findings() -> None:
    document = DocumentContext(
        width=100,
        height=100,
        selection=[],
        visual_snapshot={"png_path": "/tmp/page.png"},
        objects=[
            _tick("x1", axis="x", length=3.0, stroke_width=0.5),
            _tick("x2", axis="x", length=9.0, stroke_width=1.5),
            _tick("x3", axis="x", length=3.0, stroke_width=0.5),
            _tick("y1", axis="y", length=5.0, stroke_width=0.5),
            _tick("y2", axis="y", length=5.0, stroke_width=0.5),
            _tick("y3", axis="y", length=5.0, stroke_width=0.5),
        ],
        panels=[],
    )

    qa = publication_qa(document)
    axis_002 = [item for item in qa["findings"] if item["rule_id"] == "AXIS-002"]
    assert len(axis_002) == 1
    assert axis_002[0]["target_selector"] == {"role": "axis_tick", "axis": "x"}

    actions = [action.to_dict() for action in safe_publication_actions(document, qa)]
    assert {"kind": "set_tick_length", "params": {"role": "axis_tick", "length_px": 3.0, "axis": "x"}} in actions
    assert not any(action["kind"] == "set_tick_length" and "axis" not in action["params"] for action in actions)


def _panel(label: str, left: float, top: float) -> PanelInfo:
    return PanelInfo(
        label=label,
        label_object_id=f"label-{label}",
        label_bbox={"left": left, "top": top, "width": 5.0, "height": 5.0},
        bbox={"left": left, "top": top, "width": 40.0, "height": 30.0},
        object_count=10,
    )


def test_clean_panel_grid_is_not_flagged_as_misaligned() -> None:
    document = DocumentContext(
        width=120,
        height=100,
        selection=[],
        visual_snapshot={"png_path": "/tmp/page.png"},
        objects=[],
        panels=[
            _panel("a", 0.0, 0.0),
            _panel("b", 60.0, 0.0),
            _panel("c", 0.0, 50.0),
            _panel("d", 60.0, 50.0),
        ],
    )

    qa = publication_qa(document)
    assert "PANEL-004" not in [item["rule_id"] for item in qa["findings"]]


def test_panel_grid_misalignment_is_flagged() -> None:
    document = DocumentContext(
        width=120,
        height=100,
        selection=[],
        visual_snapshot={"png_path": "/tmp/page.png"},
        objects=[],
        panels=[
            _panel("a", 0.0, 0.0),
            _panel("b", 60.0, 5.0),
            _panel("c", 0.0, 50.0),
            _panel("d", 60.0, 50.0),
        ],
    )

    qa = publication_qa(document)
    assert "PANEL-004" in [item["rule_id"] for item in qa["findings"]]
