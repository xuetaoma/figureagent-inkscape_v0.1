from inkscape_copilot.schema import Action


def test_resize_plot_width_accepts_percent_without_selector() -> None:
    action = Action.from_dict({"kind": "resize_plot_width", "params": {"percent": 50.0}})
    assert action.to_dict() == {"kind": "resize_plot_width", "params": {"percent": 50.0}}


def test_resize_plot_width_accepts_target_width_with_panel_selector() -> None:
    action = Action.from_dict({"kind": "resize_plot_width", "params": {"panel": "c", "width": 120.0}})
    assert action.kind == "resize_plot_width"
    assert action.params["panel"] == "c"
    assert action.params["width"] == 120.0


def test_resize_plot_height_requires_percent_or_height() -> None:
    try:
        Action.from_dict({"kind": "resize_plot_height", "params": {"panel": "c"}})
    except ValueError as exc:
        assert "height or percent" in str(exc)
    else:
        raise AssertionError("Expected resize_plot_height to reject missing size.")


def test_create_polygon_accepts_regular_polygon_params() -> None:
    action = Action.from_dict(
        {"kind": "create_polygon", "params": {"cx": 50.0, "cy": 50.0, "radius": 20.0, "count": 5}}
    )
    assert action.params["degrees"] == 0.0


def test_create_polygon_accepts_custom_points() -> None:
    action = Action.from_dict(
        {
            "kind": "create_polygon",
            "params": {
                "points": [
                    {"x": 10.0, "y": 10.0},
                    {"x": 40.0, "y": 12.0},
                    {"x": 30.0, "y": 35.0},
                ]
            },
        }
    )
    assert action.params["points"][0] == {"x": 10.0, "y": 10.0}
    assert action.params["degrees"] == 0.0


def test_create_polygon_requires_regular_params_or_points() -> None:
    try:
        Action.from_dict({"kind": "create_polygon", "params": {"cx": 50.0, "cy": 50.0}})
    except ValueError as exc:
        assert "points" in str(exc)
    else:
        raise AssertionError("Expected create_polygon to reject incomplete params.")
