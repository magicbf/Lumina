"""Small Windows-specific touches layered on top of Qt."""

from __future__ import annotations

import ctypes
import sys

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _dwm():  # pragma: no cover - platform specific
    try:
        return ctypes.windll.dwmapi
    except Exception:
        return None


def _hwnd(widget) -> int | None:
    if not _is_windows():
        return None
    try:
        return int(widget.winId())
    except Exception:
        return None


def apply_dark_window(widget) -> None:
    """Ask DWM to render native bits (dialogs, shadows) in dark mode."""
    hwnd = _hwnd(widget)
    if hwnd is None:
        return
    dwm = _dwm()
    if dwm is None:
        return
    try:
        enabled = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(enabled),
            ctypes.sizeof(enabled),
        )
    except Exception:
        pass


def set_border_colour(widget, colour: str = "#101218") -> None:
    """Tint the 1px DWM frame so no bright line appears around the app."""
    hwnd = _hwnd(widget)
    if hwnd is None:
        return
    dwm = _dwm()
    if dwm is None:
        return
    try:
        value = colour.lstrip("#")
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
        colorref = ctypes.c_int(b << 16 | g << 8 | r)
        dwm.DwmSetWindowAttribute(
            hwnd, DWMWA_BORDER_COLOR, ctypes.byref(colorref), ctypes.sizeof(colorref)
        )
    except Exception:
        pass


def set_app_user_model_id(app_id: str = "Lumina.ImageViewer.1") -> None:
    """Give the app its own taskbar identity (and therefore icon grouping)."""
    if not _is_windows():
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def reveal_in_explorer(path: str) -> None:
    """Open Explorer with the given file selected."""
    import subprocess

    if _is_windows():
        try:
            subprocess.Popen(["explorer", "/select,", path])
            return
        except Exception:
            pass
    import os

    folder = os.path.dirname(path) or "."
    try:
        if _is_windows():
            subprocess.Popen(["explorer", folder])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass
