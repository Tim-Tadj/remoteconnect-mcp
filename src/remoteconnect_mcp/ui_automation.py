"""Guarded UI automation for RemoteConnect DTM functions.

RemoteConnect 4.6 exposes its DTM popup menus as WPF popups without UIA menu
items. We anchor the two relative menu locations to the main window, while all
project, dialog, and input controls use stable AutomationIds.
"""

from __future__ import annotations

import time
from pathlib import Path

from .remoteconnect import DEFAULT_LOG_DIR, read_feedback


class RemoteConnectUiError(RuntimeError):
    pass


def _connect():
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        window = desktop.window(title="RemoteConnect", control_type="Window")
        window.wait("exists enabled visible", timeout=10)
        return desktop, window
    except Exception as exc:
        raise RemoteConnectUiError(
            "Could not connect to a running RemoteConnect main window"
        ) from exc


def ui_status() -> dict:
    _, window = _connect()
    pane = window.descendants(control_type="Custom")
    project_title = next(
        (item.window_text() for item in pane if item.window_text().startswith("RemoteConnect - ")),
        "",
    )
    controllers = [
        item.element_info.automation_id
        for item in window.descendants(control_type="TreeItem")
        if item.element_info.automation_id.endswith("-DeviceDTM")
    ]
    return {
        "running": True,
        "window_title": window.window_text(),
        "project_title": project_title,
        "controller_dtms": controllers,
        "native_excel_import_available": bool(controllers),
    }


def import_excel(
    workbook_path: str,
    expected_project_title: str,
    *,
    confirm_import: bool,
    timeout_seconds: int = 300,
) -> dict:
    """Run the native DTM Import from Excel function on the open project."""
    if not confirm_import:
        raise RemoteConnectUiError(
            "confirm_import must be true because this changes the open RemoteConnect project"
        )
    workbook = Path(workbook_path).expanduser().resolve()
    if not workbook.is_file() or workbook.suffix.lower() != ".xls":
        raise RemoteConnectUiError(f"RemoteConnect XLS workbook not found: {workbook}")
    if timeout_seconds < 10 or timeout_seconds > 1800:
        raise RemoteConnectUiError("timeout_seconds must be between 10 and 1800")
    _, window = _connect()
    status = ui_status()
    actual_title = status["project_title"]
    if not expected_project_title.strip() or expected_project_title not in actual_title:
        raise RemoteConnectUiError(
            f"Open-project guard failed: expected {expected_project_title!r} within {actual_title!r}"
        )
    controllers = status["controller_dtms"]
    if len(controllers) != 1:
        raise RemoteConnectUiError(
            f"Expected exactly one controller DeviceDTM, found {len(controllers)}: {controllers}"
        )

    before = {item.resolve() for item in DEFAULT_LOG_DIR.glob("ObjectBulkEditLog_*.txt")}
    try:
        from pywinauto import keyboard, mouse

        keyboard.send_keys("{ESC}")
        window.restore()
        window.set_focus()
        window.child_window(
            auto_id=controllers[0], control_type="TreeItem"
        ).click_input()
        window.child_window(
            auto_id="dtmMenuToggleButton", control_type="Button"
        ).click_input()
        time.sleep(0.3)
        rect = window.rectangle()
        # RemoteConnect 4.6 DTM menu: Additional Functions, then Import from Excel File.
        mouse.move(coords=(rect.left + 80, rect.top + 319))
        time.sleep(0.4)
        mouse.click(coords=(rect.left + 230, rect.top + 367))
        dialog = window.child_window(title="Import from Excel File", control_type="Window")
        dialog.wait("exists enabled visible", timeout=10)
        dialog.child_window(auto_id="_txtFileName", control_type="Edit").set_edit_text(
            str(workbook)
        )
        dialog.child_window(auto_id="BtnOk", control_type="Button").click_input()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not dialog.exists(timeout=0.2):
                break
            time.sleep(0.5)
        else:
            raise RemoteConnectUiError(
                f"RemoteConnect import did not finish within {timeout_seconds} seconds"
            )
    except RemoteConnectUiError:
        raise
    except Exception as exc:
        raise RemoteConnectUiError(f"RemoteConnect native Excel import failed: {exc}") from exc

    time.sleep(1.0)
    after = {item.resolve() for item in DEFAULT_LOG_DIR.glob("ObjectBulkEditLog_*.txt")}
    new_logs = sorted(after - before, key=lambda item: item.stat().st_mtime)
    feedback = (
        read_feedback(str(new_logs[-1]))
        if new_logs
        else {"files": [], "events": [], "summary": {}, "ok": None}
    )
    return {
        "imported": str(workbook),
        "project_title": actual_title,
        "native_dialog_completed": True,
        "new_feedback_logs": [str(item) for item in new_logs],
        "feedback": feedback,
        "project_saved": False,
        "next_step": "Review feedback, then save the RemoteConnect project to an explicitly chosen copy.",
    }
