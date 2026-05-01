from pathlib import Path

from inkscape_copilot import inkscape_control, platform_support


def test_default_runtime_root_has_windows_location() -> None:
    original = platform_support.system_name
    try:
        platform_support.system_name = lambda: "windows"  # type: ignore[assignment]
        root = platform_support.default_runtime_root()
    finally:
        platform_support.system_name = original  # type: ignore[assignment]

    assert isinstance(root, Path)
    assert "FigureAgentForInkscape" in str(root)


def test_non_macos_menu_trigger_returns_clear_error() -> None:
    original_is_macos = inkscape_control.is_macos
    original_is_windows = inkscape_control.is_windows
    try:
        inkscape_control.is_macos = lambda: False  # type: ignore[assignment]
        inkscape_control.is_windows = lambda: True  # type: ignore[assignment]
        ok, error = inkscape_control.trigger_copilot_menu_item("Apply FigureAgent Changes")
    finally:
        inkscape_control.is_macos = original_is_macos  # type: ignore[assignment]
        inkscape_control.is_windows = original_is_windows  # type: ignore[assignment]

    assert ok is False
    assert error is not None
    assert "Windows" in error
