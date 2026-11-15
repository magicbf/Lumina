"""Lumina — entry point.

    python main.py            # open the gallery
    python main.py photo.jpg  # open a photo straight into the full-screen viewer
"""

from __future__ import annotations

import os
import sys
import traceback

from lumina import log

LOG_FILE = log.install()

from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from lumina import native  # noqa: E402
from lumina.icons import make_app_icon  # noqa: E402
from lumina.theme import base_qss, pick_ui_font  # noqa: E402
from lumina.window import MainWindow  # noqa: E402


def _fatal(message: str) -> None:
    """Last-resort dialog for a windowed build that has no console."""
    title = "Lumina"
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def _run() -> int:
    native.set_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName("Lumina")
    app.setApplicationDisplayName("Lumina")
    app.setOrganizationName("Lumina")
    app.setDesktopFileName("Lumina")
    app.setStyle("Fusion")

    family = pick_ui_font()
    font = QFont(family)
    font.setPointSizeF(9.75)
    app.setFont(font)
    app.setStyleSheet(base_qss(family))
    app.setWindowIcon(make_app_icon())

    app.lastWindowClosed.connect(lambda: print("last window closed", flush=True))
    app.aboutToQuit.connect(lambda: print("event loop quit", flush=True))

    window = MainWindow()
    window.show()

    # `python main.py <image>` jumps straight into the viewer.
    if len(sys.argv) > 1:
        target = os.path.abspath(sys.argv[1])
        if os.path.isfile(target):
            window.open_path(target)
        elif os.path.isdir(target):
            window.load_folder(target)

    return app.exec()


def main() -> int:
    if "--uninstall" in sys.argv[1:]:
        # Registered in Windows' "Apps & features" as `Lumina.exe --uninstall`.
        from lumina.setup.ui import run_uninstaller

        return run_uninstaller(silent="--silent" in sys.argv[1:])
    try:
        code = _run()
    except Exception:
        traceback.print_exc()
        _fatal(
            "Lumina hit an unexpected error and has to stop.\n\n"
            f"Details were written to:\n{LOG_FILE}"
        )
        return 1
    print(f"[{LOG_FILE}] exited with code {code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
