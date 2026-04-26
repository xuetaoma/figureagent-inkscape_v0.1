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
