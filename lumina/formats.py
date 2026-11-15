"""Which image formats Lumina can open, and the Pillow fallback decoder.

Qt's own plugins cover PNG, JPEG, WebP (including animated), GIF, BMP, TIFF,
ICO, TGA, ICNS and SVG, and they are used first because they are fast.

Anything Qt cannot read falls back to Pillow, which adds AVIF, JPEG 2000,
PSD, QOI, DDS, PCX and more.  If the optional ``pillow-heif`` (HEIC/HEIF, the
iPhone format) and ``pillow-jxl-plugin`` (JPEG XL) packages are installed they
are registered too.  Every Pillow import is optional: without it Lumina simply
opens fewer formats.
"""

from __future__ import annotations

try:  # Pillow is optional
    from PIL import Image, ImageOps

    HAVE_PILLOW = True
except Exception:  # pragma: no cover - depends on the environment
    Image = ImageOps = None  # type: ignore[assignment]
    HAVE_PILLOW = False

from PyQt6.QtGui import QImage

# Formats decoded by Qt itself.
QT_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".gif", ".bmp",
    ".tif", ".tiff", ".ico", ".svg", ".svgz", ".tga", ".icns",
}  # fmt: skip

# Formats we only offer when Pillow (+ its plugins) can really decode them.
PILLOW_SUFFIXES = {
    ".avif", ".heic", ".heif", ".hif", ".jxl", ".jp2", ".j2k", ".jpx",
    ".qoi", ".psd", ".pcx", ".dds", ".mpo",
}  # fmt: skip

OPTIONAL_PLUGINS: dict[str, bool] = {}


def _register_plugins() -> None:
    if not HAVE_PILLOW:
        return
    for name, module in (("HEIC/HEIF", "pillow_heif"), ("JPEG XL", "pillow_jxl")):
        try:
            imported = __import__(module)
            if module == "pillow_heif":
                imported.register_heif_opener()
            OPTIONAL_PLUGINS[name] = True
        except Exception:
            OPTIONAL_PLUGINS[name] = False


_register_plugins()


def _pillow_suffixes() -> set[str]:
    if not HAVE_PILLOW:
        return set()
    known = {ext.lower() for ext in Image.registered_extensions()}
    return {ext for ext in PILLOW_SUFFIXES if ext in known}


IMAGE_SUFFIXES: set[str] = QT_SUFFIXES | _pillow_suffixes()

_FILTER_PATTERNS = " ".join(f"*{ext}" for ext in sorted(IMAGE_SUFFIXES))
IMAGE_FILTER = f"Images ({_FILTER_PATTERNS})"


def hint() -> str:
    """Short list of headline formats for the empty-state caption."""
    names = ["PNG", "JPG", "WEBP"]
    for ext, label in ((".avif", "AVIF"), (".heic", "HEIC"), (".jxl", "JXL")):
        if ext in IMAGE_SUFFIXES:
            names.append(label)
    names += ["GIF", "BMP", "TIFF", "SVG"]
    return "  ·  ".join(names)


def decode_pillow(path: str, cover_px: int | None = None) -> QImage:
    """Decode *path* with Pillow into a QImage (null on failure).

    With *cover_px* the image is shrunk so that its shorter side is about that
    many pixels — enough for a thumbnail, and much cheaper to hand over.
    """
    if not HAVE_PILLOW:
        return QImage()
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened)
            if image is None:
                image = opened
            if cover_px:
                shorter = min(image.size)
                if shorter > cover_px:
                    ratio = cover_px / shorter
                    size = (
                        max(1, round(image.width * ratio)),
                        max(1, round(image.height * ratio)),
                    )
                    image = image.resize(
                        size, Image.Resampling.BILINEAR, reducing_gap=2.0
                    )
            has_alpha = image.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
                "transparency" in image.info
            )
            image = image.convert("RGBA" if has_alpha else "RGB")
            width, height = image.size
            data = image.tobytes()
        if has_alpha:
            qimage = QImage(
                data, width, height, width * 4, QImage.Format.Format_RGBA8888
            )
        else:
            qimage = QImage(
                data, width, height, width * 3, QImage.Format.Format_RGB888
            )
        # Detach from `data` (the caller converts again to a native format).
        return qimage.copy()
    except Exception:
        return QImage()
