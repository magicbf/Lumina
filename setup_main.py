"""Lumina Setup — entry point of the installer executable.

    Setup.exe                      graphical installer
    Setup.exe /S [--dir PATH] [--no-start-menu] [--no-desktop] [--no-assoc]
                                   silent install (no window)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lumina.setup import ops


def _silent(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="Setup.exe")
    parser.add_argument("--dir", default=ops.default_dir())
    parser.add_argument("--no-start-menu", action="store_true")
    parser.add_argument("--no-desktop", action="store_true")
    parser.add_argument("--no-assoc", action="store_true")
    parser.add_argument("--payload")
    args, _ = parser.parse_known_args(argv)

    from PyQt6.QtCore import QCoreApplication

    app = QCoreApplication([])  # needed to locate Start menu / Desktop
    options = ops.InstallOptions(
        directory=args.dir,
        start_menu=not args.no_start_menu,
        desktop=not args.no_desktop,
        associate=not args.no_assoc,
    )
    try:
        exe = ops.install(options, payload=Path(args.payload) if args.payload else None)
    except ops.SetupError as error:
        _fatal(f"Setup failed:\n\n{error}")
        return 1
    print(f"Installed {exe}")
    del app
    return 0


def _fatal(message: str) -> None:
    """Plain error box for a windowed build that has no console."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Lumina Setup", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    flags = {arg.lower() for arg in sys.argv[1:]}
    try:
        if flags & {"/s", "--silent", "/silent", "/verysilent"}:
            return _silent(sys.argv[1:])
        from lumina.setup.ui import run_installer

        return run_installer()
    except Exception as error:
        _fatal(f"Lumina Setup could not finish.\n\n{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
