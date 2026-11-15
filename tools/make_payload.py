"""Zip the one-folder build (dist/Lumina) into dist/payload.zip for Setup.exe."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dist" / "Lumina"
OUT = ROOT / "dist" / "payload.zip"


def main() -> int:
    if not (SRC / "Lumina.exe").is_file():
        print(f"missing {SRC / 'Lumina.exe'} - run build_exe.bat first", file=sys.stderr)
        return 1
    OUT.unlink(missing_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(SRC.rglob("*")):
            archive.write(path, path.relative_to(SRC).as_posix())
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
