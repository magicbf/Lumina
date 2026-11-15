"""Render the programmatic Lumina mark into Windows icon files.

Run before packaging:  python tools/make_icon.py
Writes assets/lumina.ico.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize, Qt  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

from lumina.icons import make_app_icon  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - keeps Qt happy
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)

    icon = make_app_icon(256)
    base = out / "lumina_256.png"
    icon.pixmap(QSize(256, 256)).save(str(base), "PNG")

    from PIL import Image

    image = Image.open(base).convert("RGBA")
    ico = out / "lumina.ico"
    image.save(ico, format="ICO", sizes=[(s, s) for s in SIZES])

    base.unlink(missing_ok=True)

    print(f"wrote {ico} ({ico.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
