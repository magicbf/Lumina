"""Console-free crash logging.

The app ships as a windowed executable, so there is no terminal to print a
traceback to.  Everything worth knowing goes to

    %LOCALAPPDATA%\\Lumina\\logs\\lumina.log

which is rotated once it grows past a few hundred kilobytes.
"""

from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

MAX_BYTES = 512 * 1024


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    return root / "Lumina" / "logs"


def log_path() -> Path:
    return log_dir() / "lumina.log"


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            backup = path.with_name("lumina.1.log")
            try:
                backup.unlink()
            except OSError:
                pass
            path.replace(backup)
    except OSError:
        pass


def install() -> Path:
    """Route stderr, uncaught exceptions and Qt messages into the log file."""
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = log_path()
        _rotate(path)
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        import tempfile

        path = Path(tempfile.gettempdir()) / "lumina.log"
        stream = open(path, "a", encoding="utf-8", buffering=1)

    stream.write(f"\n--- Lumina started {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    stream.flush()

    # A windowed build has no usable stdio; point it at the log so warnings
    # from Qt or from libraries do not vanish.  Keep a real console if we have
    # one (python main.py from a terminal).
    if sys.stderr is None:
        sys.stderr = stream
    if sys.stdout is None:
        sys.stdout = stream

    try:
        faulthandler.enable(stream)
    except (OSError, ValueError):
        pass

    def hook(exc_type, exc_value, exc_tb) -> None:
        for line in traceback.format_exception(exc_type, exc_value, exc_tb):
            stream.write(line)
        stream.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] unhandled exception\n")
        stream.flush()
        if sys.__stderr__ is not None:
            traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.__stderr__)

    sys.excepthook = hook

    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

        levels = {
            QtMsgType.QtDebugMsg: "debug",
            QtMsgType.QtInfoMsg: "info",
            QtMsgType.QtWarningMsg: "warning",
            QtMsgType.QtCriticalMsg: "critical",
            QtMsgType.QtFatalMsg: "fatal",
        }

        def qt_handler(mode, context, message) -> None:
            where = ""
            if context is not None and context.file:
                where = f" ({context.file}:{context.line})"
            stream.write(f"[qt:{levels.get(mode, mode)}{where}] {message}\n")
            stream.flush()

        qInstallMessageHandler(qt_handler)
    except Exception:  # pragma: no cover - never let logging break startup
        pass

    return path
