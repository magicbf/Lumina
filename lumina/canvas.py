"""The zoomable / pannable image surface used by the full-screen viewer.

Photos are decoded on a worker thread (never on the UI thread), the neighbours
of the current photo are decoded ahead of time, and while a photo is still
loading the canvas shows its already-cached gallery thumbnail so navigation
feels instant.  Large photos also get a screen-sized preview so that fitting
and fading them is cheap; the full-resolution pixels are only used once you
zoom in far enough to need them.
"""

from __future__ import annotations

import os
from collections import OrderedDict

from PyQt6.QtCore import (
    QByteArray,
    QEasingCurve,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    QThreadPool,
    QTimer,
    QVariantAnimation,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QImageReader,
    QMovie,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget

from .formats import decode_pillow

ANIMATED_SUFFIXES = {".gif", ".webp"}

SIDE_MARGIN = 52.0
TOP_MARGIN = 76.0
BOTTOM_MARGIN = 92.0

MIN_ZOOM = 1.0
MAX_ZOOM = 20.0

CACHE_BYTES = 320 * 1024 * 1024
MIN_CACHED = 2
SETTLE_MS = 140

_OPAQUE = QImage.Format.Format_RGB32
_PREMULT = QImage.Format.Format_ARGB32_Premultiplied


def _native(image: QImage) -> QImage:
    """Convert to a format QPixmap can wrap without a per-pixel copy."""
    if image.format() in (_OPAQUE, _PREMULT):
        return image
    return image.convertToFormat(_PREMULT if image.hasAlphaChannel() else _OPAQUE)


# ---------------------------------------------------------------------------
# background decoding
# ---------------------------------------------------------------------------


class _LoadSignals(QObject):
    # path, full image, preview image.  full is None when the job was skipped
    # (no longer wanted) and a null QImage when decoding failed.
    done = pyqtSignal(str, object, object)


class _LoadJob(QRunnable):
    def __init__(self, owner: "ImageCanvas", path: str, preview_edge: int) -> None:
        super().__init__()
        self._owner = owner
        self._signals = owner._signals
        self._path = path
        self._edge = preview_edge
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D401
        full: QImage | None = None
        preview = QImage()
        try:
            if self._path in self._owner._wanted:
                reader = QImageReader(self._path)
                reader.setAutoTransform(True)
                full = reader.read()
                if full.isNull():
                    full = QImage(self._path)
                if full.isNull():
                    full = decode_pillow(self._path)
                if not full.isNull():
                    full = _native(full)
                    edge = self._edge
                    if max(full.width(), full.height()) > edge * 1.25:
                        preview = _native(
                            full.scaled(
                                QSize(edge, edge),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
        except Exception:
            full, preview = QImage(), QImage()
        try:
            self._signals.done.emit(self._path, full, preview)
        except RuntimeError:
            pass  # canvas destroyed while decoding


class _Entry:
    __slots__ = ("full", "preview", "bytes")

    def __init__(self, full: QPixmap, preview: QPixmap | None) -> None:
        self.full = full
        self.preview = preview
        self.bytes = full.width() * full.height() * 4
        if preview is not None:
            self.bytes += preview.width() * preview.height() * 4


def _screen_edge() -> int:
    edge = 1920
    for screen in QGuiApplication.screens():
        size = screen.size()
        ratio = screen.devicePixelRatio()
        edge = max(edge, int(max(size.width(), size.height()) * ratio))
    return edge


class ImageCanvas(QWidget):
    zoomChanged = pyqtSignal(int)
    activity = pyqtSignal()
    imageLoaded = pyqtSignal(bool)  # the current photo finished loading (ok?)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._path: str | None = None
        self._state = "empty"  # empty | loading | ready | failed
        self._full: QPixmap | None = None
        self._preview: QPixmap | None = None
        self._placeholder: QPixmap | None = None
        self._img_size = (0, 0)
        self._movie: QMovie | None = None
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._appear = 1.0
        self._fade = 1.0
        self._fade_anim: QVariantAnimation | None = None
        self._fade_started = False
        self._dragging = False
        self._drag_from = QPointF()
        self._pan_from = QPointF()
        self._cursor_hidden = False
        self._painted = QRectF()

        # While the user is zooming or panning a huge photo we draw it with the
        # fast sampler, then redraw it smoothly once they stop.
        self._interacting = False
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self._on_settled)

        self._cache: "OrderedDict[str, _Entry]" = OrderedDict()
        self._cache_bytes = 0
        self._failed: set[str] = set()
        self._pending: set[str] = set()
        self._wanted: frozenset[str] = frozenset()
        self._signals = _LoadSignals(self)
        self._signals.done.connect(self._on_loaded)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._preview_edge = _screen_edge()

    # -- image loading ------------------------------------------------------
    def current_path(self) -> str | None:
        return self._path

    def state(self) -> str:
        return self._state

    def source_size(self) -> tuple[int, int]:
        return self._source_size()

    def set_image(
        self,
        path: str,
        placeholder: QPixmap | None = None,
        prefetch: list[str] | tuple[str, ...] = (),
    ) -> None:
        """Show *path*.  Returns immediately; watch :attr:`imageLoaded`."""
        self._stop_movie()
        self._path = path
        self._full = self._preview = self._placeholder = None
        self._img_size = (0, 0)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._painted = QRectF()
        self._fade_started = False
        self._state = "loading"

        movie_ok = False
        suffix = os.path.splitext(path)[1].lower()
        if suffix in ANIMATED_SUFFIXES:
            movie = QMovie(path, QByteArray(), self)
            # A still WebP is cheaper (and preview-scaled) as a normal image.
            if movie.isValid() and (suffix == ".gif" or movie.frameCount() > 1):
                movie.setCacheMode(QMovie.CacheMode.CacheAll)
                movie.frameChanged.connect(self._on_frame)
                movie.start()
                self._movie = movie
                movie_ok = True
                self._state = "ready"
            else:
                movie.deleteLater()

        self._wanted = frozenset((path, *prefetch))
        if movie_ok:
            pass
        elif path in self._failed:
            self._state = "failed"
        else:
            entry = self._cache.get(path)
            if entry is not None:
                self._cache.move_to_end(path)
                self._apply(entry)
            else:
                if placeholder is not None and not placeholder.isNull():
                    self._placeholder = placeholder
                    self._img_size = self._estimate_size(path, placeholder)
                self._request(path, priority=2)

        for extra in prefetch:
            if (
                extra not in self._cache
                and extra not in self._failed
                and os.path.splitext(extra)[1].lower() not in ANIMATED_SUFFIXES
            ):
                self._request(extra, priority=1)

        if self._state != "loading" or self._placeholder is not None:
            self._play_fade()
        self.zoomChanged.emit(self.zoom_percent())
        self._update_cursor()
        self.update()
        if self._state != "loading":
            self.imageLoaded.emit(self._state == "ready")

    def release(self) -> None:
        """Drop decoded photos (the viewer was closed)."""
        self._wanted = frozenset()
        self._cache.clear()
        self._cache_bytes = 0
        self._full = self._preview = self._placeholder = None
        self._state = "empty"
        self._path = None
        self._stop_movie()

    @staticmethod
    def _estimate_size(path: str, placeholder: QPixmap) -> tuple[int, int]:
        """Real photo size from its header, oriented like the thumbnail."""
        width, height = placeholder.width(), placeholder.height()
        try:
            size = QImageReader(path).size()
            if size.isValid() and size.width() > 0 and size.height() > 0:
                w, h = size.width(), size.height()
                if (w >= h) != (width >= height):
                    w, h = h, w
                return (w, h)
        except Exception:
            pass
        return (width, height)

    def _request(self, path: str, priority: int) -> None:
        if path in self._pending:
            return
        self._pending.add(path)
        self._pool.start(_LoadJob(self, path, self._preview_edge), priority)

    def _on_loaded(self, path: str, full, preview) -> None:
        self._pending.discard(path)
        if full is None:  # skipped: it was not wanted when the worker got to it
            if path in self._wanted and path not in self._cache:
                # ...but it is wanted again now (user navigated back): redo it.
                self._request(path, priority=2 if path == self._path else 1)
            return
        if full.isNull():
            self._failed.add(path)
            if path == self._path and self._state == "loading":
                self._state = "failed"
                self._placeholder = None
                self.update()
                self.imageLoaded.emit(False)
            return

        entry = _Entry(
            QPixmap.fromImage(full),
            QPixmap.fromImage(preview) if not preview.isNull() else None,
        )
        old = self._cache.pop(path, None)
        if old is not None:
            self._cache_bytes -= old.bytes
        self._cache[path] = entry
        self._cache_bytes += entry.bytes
        while self._cache_bytes > CACHE_BYTES and len(self._cache) > MIN_CACHED:
            key = next(iter(self._cache))
            if key == self._path:
                self._cache.move_to_end(key)
                continue
            self._cache_bytes -= self._cache.pop(key).bytes

        if path == self._path and self._state == "loading" and self._movie is None:
            self._apply(entry)
            self._placeholder_done()
            self.zoomChanged.emit(self.zoom_percent())
            self._update_cursor()
            self.update()
            self.imageLoaded.emit(True)

    def _placeholder_done(self) -> None:
        if not self._fade_started:
            self._play_fade()

    def _apply(self, entry: _Entry) -> None:
        self._full = entry.full
        self._preview = entry.preview
        self._placeholder = None
        self._img_size = (entry.full.width(), entry.full.height())
        self._state = "ready"
        self._clamp_pan()

    def _on_frame(self, frame: int) -> None:
        if self._movie is not None:
            self.update()

    def _stop_movie(self) -> None:
        if self._movie is not None:
            try:
                self._movie.frameChanged.disconnect(self._on_frame)
            except Exception:
                pass
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_movie()
        self._wanted = frozenset()
        self._pool.clear()
        super().closeEvent(event)

    # -- geometry helpers ---------------------------------------------------
    def _frame_pixmap(self) -> QPixmap | None:
        if self._movie is not None:
            frame = self._movie.currentPixmap()
            return frame if not frame.isNull() else None
        return self._full

    def _source_size(self) -> tuple[int, int]:
        if self._movie is not None:
            pixmap = self._frame_pixmap()
            return (0, 0) if pixmap is None else (pixmap.width(), pixmap.height())
        return self._img_size

    def _avail(self) -> QRectF:
        return QRectF(
            SIDE_MARGIN,
            TOP_MARGIN,
            max(40.0, self.width() - SIDE_MARGIN * 2),
            max(40.0, self.height() - TOP_MARGIN - BOTTOM_MARGIN),
        )

    def _fit_scale(self) -> float:
        w, h = self._source_size()
        if w <= 0 or h <= 0:
            return 1.0
        avail = self._avail()
        scale = min(avail.width() / w, avail.height() / h)
        return max(0.01, min(scale, 4.0))

    def _scale(self) -> float:
        return self._fit_scale() * self._zoom

    def image_rect(self) -> QRectF:
        w, h = self._source_size()
        if w <= 0 or h <= 0:
            return QRectF()
        scale = self._scale()
        width, height = w * scale, h * scale
        centre = QPointF(self.width() / 2, self.height() / 2) + self._pan
        return QRectF(
            centre.x() - width / 2, centre.y() - height / 2, width, height
        )

    def zoom_percent(self) -> int:
        return int(round(self._scale() * 100))

    def can_pan(self) -> bool:
        rect = self.image_rect()
        if rect.isEmpty():
            return False
        avail = self._avail()
        return rect.width() > avail.width() + 1 or rect.height() > avail.height() + 1

    def _invalidate(self) -> None:
        """Repaint only the area the photo covers (old and new position)."""
        region = self.image_rect()
        if not self._painted.isNull():
            region = region.united(self._painted) if not region.isNull() else self._painted
        if region.isNull() or region.isEmpty():
            self.update()
        else:
            self.update(region.adjusted(-3, -3, 3, 3).toAlignedRect())

    def _interact(self) -> None:
        self._interacting = True
        self._settle.start()

    def _on_settled(self) -> None:
        self._interacting = False
        self._invalidate()

    # -- zoom / pan ---------------------------------------------------------
    def fit(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.zoomChanged.emit(self.zoom_percent())
        self._update_cursor()
        self._invalidate()

    def actual_size(self) -> None:
        fit = self._fit_scale()
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, 1.0 / fit if fit > 0 else 1.0))
        self._pan = QPointF(0.0, 0.0)
        self.zoomChanged.emit(self.zoom_percent())
        self._update_cursor()
        self._invalidate()

    def set_zoom_percent(self, percent: float) -> None:
        fit = self._fit_scale()
        zoom = (percent / 100.0) / fit if fit > 0 else 1.0
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if self._zoom <= MIN_ZOOM + 1e-6:
            self._pan = QPointF(0.0, 0.0)
        self.zoomChanged.emit(self.zoom_percent())
        self._update_cursor()
        self._invalidate()

    def zoom_by(self, factor: float) -> None:
        centre = QPointF(self.width() / 2, self.height() / 2)
        self._zoom_at(self._zoom * factor, centre)

    def _zoom_at(self, zoom: float, anchor: QPointF) -> None:
        if self._source_size()[0] <= 0:
            return
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        fit = self._fit_scale()
        old_scale = fit * self._zoom
        new_scale = fit * new_zoom
        centre = QPointF(self.width() / 2, self.height() / 2)
        offset = anchor - centre - self._pan
        if old_scale > 0:
            image_point = offset / old_scale
            self._pan = anchor - centre - image_point * new_scale
        self._zoom = new_zoom
        if new_zoom <= MIN_ZOOM + 1e-6:
            self._pan = QPointF(0.0, 0.0)
        self._clamp_pan()
        self._interact()
        self.zoomChanged.emit(self.zoom_percent())
        self._update_cursor()
        self._invalidate()

    def _clamp_pan(self) -> None:
        w, h = self._source_size()
        if w <= 0 or h <= 0:
            self._pan = QPointF(0.0, 0.0)
            return
        scale = self._scale()
        avail = self._avail()
        max_x = max(0.0, (w * scale - avail.width()) / 2.0)
        max_y = max(0.0, (h * scale - avail.height()) / 2.0)
        self._pan = QPointF(
            max(-max_x, min(max_x, self._pan.x())),
            max(-max_y, min(max_y, self._pan.y())),
        )

    # -- animation ----------------------------------------------------------
    def _play_fade(self) -> None:
        if self._fade_anim is not None:
            self._fade_anim.stop()
        self._fade_started = True
        self._fade = 0.0
        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._set_fade)
        self._fade_anim = anim
        anim.start()

    def _set_fade(self, value) -> None:
        self._fade = float(value)
        self._invalidate()

    def set_appear(self, value: float) -> None:
        self._appear = value
        self._invalidate()

    # -- input --------------------------------------------------------------
    def _set_cursor_hidden(self, hidden: bool) -> None:
        self._cursor_hidden = hidden
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._cursor_hidden:
            self.setCursor(Qt.CursorShape.BlankCursor)
        elif self._dragging:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self.can_pan():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.activity.emit()
        if event.button() == Qt.MouseButton.LeftButton and self.can_pan():
            self._dragging = True
            self._drag_from = event.position()
            self._pan_from = QPointF(self._pan)
            self._update_cursor()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.activity.emit()
        if self._dragging:
            delta = event.position() - self._drag_from
            self._pan = self._pan_from + delta
            self._clamp_pan()
            self._interact()
            self._invalidate()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._update_cursor()
        self.activity.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._zoom <= MIN_ZOOM + 1e-6:
            self.actual_size()
        else:
            self.fit()
        self.activity.emit()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._zoom_at(self._zoom * (1.0019 ** delta), event.position())
        self.activity.emit()

    # -- painting -----------------------------------------------------------
    def _paint_source(self, target_width: float) -> tuple[QPixmap | None, bool]:
        """Pick the cheapest pixmap that is still sharp at *target_width*."""
        if self._movie is not None:
            return self._frame_pixmap(), False
        if self._full is None:
            return self._placeholder, False
        preview = self._preview
        if preview is not None:
            needed = target_width * self.devicePixelRatioF()
            if needed <= preview.width() + 1:
                return preview, False
        return self._full, True

    def paintEvent(self, event) -> None:  # noqa: N802
        rect = self.image_rect()
        if rect.isEmpty():
            return
        pixmap, is_full = self._paint_source(rect.width())
        if pixmap is None or pixmap.isNull():
            return

        p = QPainter(self)
        fast = is_full and self._interacting
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not fast)

        grow = 0.965 + 0.035 * max(0.0, min(1.0, self._appear))
        if grow < 1.0:
            centre = rect.center()
            rect = QRectF(
                centre.x() - rect.width() * grow / 2,
                centre.y() - rect.height() * grow / 2,
                rect.width() * grow,
                rect.height() * grow,
            )

        p.setOpacity(max(0.0, min(1.0, self._fade * self._appear)))
        p.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))

        p.setOpacity(self._appear)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(255, 255, 255, 34))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5))
        p.end()
        self._painted = rect

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._clamp_pan()
        self.zoomChanged.emit(self.zoom_percent())
