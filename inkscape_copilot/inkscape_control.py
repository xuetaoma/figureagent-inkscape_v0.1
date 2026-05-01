from __future__ import annotations

import subprocess

from .platform_support import is_macos, is_windows


def _copilot_menu_script(menu_item_name: str, *, auto_confirm: bool = False) -> str:
    auto_confirm_block = ""
    if auto_confirm:
        auto_confirm_block = """
\t\trepeat 20 times
\t\t\ttry
\t\t\t\tif exists sheet 1 of window 1 then
\t\t\t\t\tif exists button \"OK\" of sheet 1 of window 1 then
\t\t\t\t\t\tclick button \"OK\" of sheet 1 of window 1
\t\t\t\t\t\texit repeat
\t\t\t\t\tend if
\t\t\t\t\tif exists button \"Apply\" of sheet 1 of window 1 then
\t\t\t\t\t\tclick button \"Apply\" of sheet 1 of window 1
\t\t\t\t\t\texit repeat
\t\t\t\t\tend if
\t\t\t\tend if
\t\t\tend try
\t\t\ttry
\t\t\t\tif exists button \"OK\" of window 1 then
\t\t\t\t\tclick button \"OK\" of window 1
\t\t\t\t\texit repeat
\t\t\t\tend if
\t\t\t\tif exists button \"Apply\" of window 1 then
\t\t\t\t\tclick button \"Apply\" of window 1
\t\t\t\t\texit repeat
\t\t\t\tend if
\t\t\tend try
\t\t\tdelay 0.15
\t\tend repeat
\t\ttry
\t\t\tkey code 36
\t\tend try
"""
    return f'''
on findMenuItemByName(parentMenu, targetName)
\ttell application "System Events"
\t\trepeat with candidateItem in menu items of parentMenu
\t\t\ttry
\t\t\t\tif name of candidateItem is targetName then return candidateItem
\t\t\tend try
\t\t\ttry
\t\t\t\tset nestedItem to my findMenuItemByName(menu 1 of candidateItem, targetName)
\t\t\t\tif nestedItem is not missing value then return nestedItem
\t\t\tend try
\t\tend repeat
\tend tell
\treturn missing value
end findMenuItemByName

tell application "Inkscape" to activate
delay 0.5
tell application "System Events"
\ttell process "inkscape"
\t\tset frontmost to true
\t\tset foundExtensions to false
\t\trepeat 20 times
\t\t\tif exists menu bar item "Extensions" of menu bar 1 then
\t\t\t\tset foundExtensions to true
\t\t\t\texit repeat
\t\t\tend if
\t\t\tdelay 0.25
\t\tend repeat
\t\tif foundExtensions is false then
\t\t\terror "Open or focus an Inkscape document window before running FigureAgent commands."
\t\tend if
\t\tclick menu bar item "Extensions" of menu bar 1
\t\tdelay 0.2
\t\tset extensionsMenu to menu 1 of menu bar item "Extensions" of menu bar 1
\t\tset targetItem to missing value
\t\ttry
\t\t\tif exists menu item "FigureAgent" of extensionsMenu then
\t\t\t\tclick menu item "FigureAgent" of extensionsMenu
\t\t\t\tdelay 0.2
\t\t\t\tset targetItem to my findMenuItemByName(menu 1 of menu item "FigureAgent" of extensionsMenu, "{menu_item_name}")
\t\t\tend if
\t\t\tif targetItem is missing value and exists menu item "Copilot" of extensionsMenu then
\t\t\t\tclick menu item "Copilot" of extensionsMenu
\t\t\t\tdelay 0.2
\t\t\t\tset targetItem to my findMenuItemByName(menu 1 of menu item "Copilot" of extensionsMenu, "{menu_item_name}")
\t\t\tend if
\t\tend try
\t\tif targetItem is missing value then
\t\t\tset targetItem to my findMenuItemByName(extensionsMenu, "{menu_item_name}")
\t\tend if
\t\tif targetItem is missing value then
\t\t\terror "Could not find Inkscape extension menu item: {menu_item_name}"
\t\tend if
\t\tperform action "AXPress" of targetItem
{auto_confirm_block}\t
\tend tell
end tell
'''


def trigger_copilot_menu_item(menu_item_name: str, *, auto_confirm: bool = False) -> tuple[bool, str | None]:
    if not is_macos():
        if is_windows():
            return (
                False,
                "Automatic Inkscape menu triggering is not implemented on Windows yet. "
                f"Use Extensions -> FigureAgent -> {menu_item_name}, or run the MCP/tool flow and apply manually.",
            )
        return (
            False,
            "Automatic Inkscape menu triggering currently requires macOS AppleScript. "
            f"Use Extensions -> FigureAgent -> {menu_item_name} manually on this platform.",
        )

    script = _copilot_menu_script(menu_item_name, auto_confirm=auto_confirm)
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0 if auto_confirm else 2.5,
        )
    except subprocess.TimeoutExpired:
        # On macOS, System Events can block waiting for Inkscape to finish the
        # command even after the menu item has already been dispatched.
        return True, None
    except Exception as exc:
        return False, str(exc)

    if result.returncode == 0:
        return True, None

    stderr = result.stderr.strip() or result.stdout.strip() or "Unknown AppleScript error"
    return False, stderr


def trigger_apply_pending_jobs() -> tuple[bool, str | None]:
    ok, error = trigger_copilot_menu_item("Apply FigureAgent Changes", auto_confirm=True)
    if ok:
        return ok, error
    legacy_ok, legacy_error = trigger_copilot_menu_item("Apply Copilot Changes", auto_confirm=True)
    return (legacy_ok, legacy_error) if legacy_ok else (ok, error)


def trigger_sync_document_state() -> tuple[bool, str | None]:
    return trigger_copilot_menu_item("Refresh FigureAgent Context")
