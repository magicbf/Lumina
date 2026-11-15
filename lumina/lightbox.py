"""Full-screen photo viewer: a 50 % black translucent veil with floating HUD."""

from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QCursor,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import native
from .canvas import ImageCanvas
from .gallery import _cover_source
from .icons import IconButton, PillButton
from .theme import (
    ACCENT,
    DANGER,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
    VEIL_ALPHA,
)
from .thumbs import ThumbnailService
from .ui import Divider, ElideLabel, add_action, make_menu


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def _metadata(path: str, dimensions: tuple[int, int]) -> str:
    parts: list[str] = []
    width, height = dimensions
    if width and height:
        parts.append(f"{width} × {height}")
    try:
        stat = os.stat(path)
        parts.append(_human_size(stat.st_size))
        parts.append(datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y"))
    except OSError:
        pass
    return "   ·   ".join(parts)


# ---------------------------------------------------------------------------
# filmstrip
# ---------------------------------------------------------------------------

FILM_CELL = 54
FILM_GAP = 6


class _FilmCell(QAbstractButton):
    def __init__(
        self,
        path: str,
        index: int,
        thumbs: ThumbnailService,
        px: int = 108,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.index = index
        self._thumbs = thumbs
        self._px = px
        self._thumb = thumbs.cached(path, px)
        if self._thumb is None:
            # Re-use the gallery's bigger thumbnail instead of decoding again.
            self._thumb = thumbs.any_cached(path)
            if self._thumb is None:
                thumbs.request(path, px)
        self._current = False
        self.setFixedSize(FILM_CELL, FILM_CELL)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def apply_thumb(self, path: str, px: int, pixmap: QPixmap) -> bool:
        if path == self.path and px == self._px:
            self._thumb = pixmap
            self.update()
            return True
        return False

    def set_current(self, current: bool) -> None:
        if current != self._current:
            self._current = current
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        frame = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)

        clip = QPainterPath()
        clip.addRoundedRect(frame, 8.0, 8.0)
        p.setClipPath(clip)
        p.fillPath(clip, QColor(255, 255, 255, 12))

        if self._thumb is not None and not self._thumb.isNull():
            p.drawPixmap(frame, self._thumb, _cover_source(self._thumb, frame))
        if not self._current:
            p.fillPath(clip, QColor(0, 0, 0, 110))
        p.setClipping(False)

        if self._current:
            pen = QPen(QColor(ACCENT))
            pen.setWidthF(1.8)
        else:
            pen = QPen(QColor(255, 255, 255, 28))
            pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(frame, 8.0, 8.0)
        p.end()


class Filmstrip(QFrame):
    goTo = pyqtSignal(int)

    WINDOW = 10

    def __init__(self, thumbs: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hud")
        self.setFixedHeight(84)
        self._thumbs = thumbs
        self._paths: list[str] = []
        self._index = 0
        self._start = 0
        self._end = 0
        self._cells: dict[int, _FilmCell] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent;")

        self.inner = QWidget()
        self.inner.setObjectName("filmInner")
        self.scroll.setWidget(self.inner)
        outer.addWidget(self.scroll)

        thumbs.ready.connect(self._on_thumb)

    # -- content ------------------------------------------------------------
    # Cells are positioned by hand at ``index * (FILM_CELL + FILM_GAP)`` and
    # only the ones near the current photo exist.  Moving one photo along
    # creates one cell and deletes one, instead of rebuilding all of them.
    def set_images(self, paths: list[str], index: int) -> None:
        self._paths = paths
        self._index = index
        for cell in self._cells.values():
            self._discard(cell)
        self._cells.clear()
        self._start = self._end = -1
        # Size the strip explicitly.  adjustSize() can resolve to 0x0 while the
        # viewer is hidden, which left the filmstrip blank when it was reopened.
        count = len(paths)
        width = count * FILM_CELL + max(0, count - 1) * FILM_GAP
        self.inner.setFixedSize(max(1, width), FILM_CELL)
        self._sync()

    def set_index(self, index: int) -> None:
        self._index = index
        self._sync()

    @staticmethod
    def _discard(cell: "_FilmCell") -> None:
        cell.hide()
        cell.setParent(None)
        cell.deleteLater()

    def _sync(self) -> None:
        total = len(self._paths)
        if total == 0:
            return
        start = max(0, self._index - self.WINDOW)
        end = min(total, self._index + self.WINDOW + 1)
        if start != self._start or end != self._end:
            for index in [i for i in self._cells if not start <= i < end]:
                self._discard(self._cells.pop(index))
            for index in range(start, end):
                if index in self._cells:
                    continue
                cell = _FilmCell(self._paths[index], index, self._thumbs, parent=self.inner)
                cell.move(index * (FILM_CELL + FILM_GAP), 0)
                cell.clicked.connect(lambda _=False, i=index: self.goTo.emit(i))
                cell.show()
                self._cells[index] = cell
            self._start, self._end = start, end
        for index, cell in self._cells.items():
            cell.set_current(index == self._index)
        self._centre_current()

    def _centre_current(self) -> None:
        bar = self.scroll.horizontalScrollBar()
        viewport = self.scroll.viewport().width()
        target = self._index * (FILM_CELL + FILM_GAP) - (viewport - FILM_CELL) // 2
        bar.setValue(max(0, min(bar.maximum(), target)))

    def _on_thumb(self, path: str, px: int, pixmap: QPixmap) -> None:
        for cell in self._cells.values():
            cell.apply_thumb(path, px, pixmap)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            self.goTo.emit(self._index + (1 if delta < 0 else -1))
        event.accept()


# ---------------------------------------------------------------------------
# top HUD
# ---------------------------------------------------------------------------


class TopBar(QFrame):
    def __init__(self, viewer: "Lightbox") -> None:
        super().__init__(viewer)
        self.setObjectName("hud")
        self.setFixedHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 12, 8)
        layout.setSpacing(6)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(1)
        self.name = ElideLabel("", Qt.TextElideMode.ElideMiddle)
        self.name.setObjectName("hudTitle")
        self.meta = ElideLabel("", Qt.TextElideMode.ElideRight)
        self.meta.setObjectName("hudMeta")
        titles.addWidget(self.name)
        titles.addWidget(self.meta)
        layout.addLayout(titles, 1)
        layout.addSpacing(10)

        self.counter = QLabel("– / –")
        self.counter.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 12px; padding: 0 6px;"
        )
        layout.addWidget(self.counter)
        layout.addWidget(Divider())

        self.prev_btn = IconButton(
            "chevron-left", size=30, tooltip="Previous image  (←)"
        )
        self.next_btn = IconButton(
            "chevron-right", size=30, tooltip="Next image  (→)"
        )
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.next_btn)
        layout.addWidget(Divider())

        self.zoom_out = IconButton("minus", size=30, tooltip="Zoom out  (−)")
        self.zoom_btn = PillButton("Fit", height=28, pad=8, font_px=12)
        self.zoom_btn.setFixedWidth(58)
        self.zoom_btn.setToolTip("Zoom level")
        self.zoom_in = IconButton("plus", size=30, tooltip="Zoom in  (+)")
        layout.addWidget(self.zoom_out)
        layout.addWidget(self.zoom_btn)
        layout.addWidget(self.zoom_in)

        self.fit_btn = IconButton("fit", size=30, tooltip="Fit to window  (0)")
        self.actual_btn = IconButton("actual", size=30, tooltip="Actual size  (1)")
        layout.addWidget(Divider())
        layout.addWidget(self.fit_btn)
        layout.addWidget(self.actual_btn)
        layout.addWidget(Divider())

        self.menu_btn = IconButton("dots", size=30, tooltip="More actions")
        self.close_btn = IconButton(
            "close", size=30, danger=True, tooltip="Close viewer  (Esc)"
        )
        layout.addWidget(self.menu_btn)
        layout.addWidget(self.close_btn)

        self.prev_btn.clicked.connect(viewer.prev_image)
        self.next_btn.clicked.connect(viewer.next_image)
        self.zoom_out.clicked.connect(viewer.zoom_out)
        self.zoom_in.clicked.connect(viewer.zoom_in)
        self.zoom_btn.clicked.connect(
            lambda: viewer.zoom_menu(self.zoom_btn.mapToGlobal(QPoint(0, 34)))
        )
        self.fit_btn.clicked.connect(viewer.fit)
        self.actual_btn.clicked.connect(viewer.actual_size)
        self.menu_btn.clicked.connect(
            lambda: viewer.action_menu(self.menu_btn.mapToGlobal(QPoint(-150, 34)))
        )
        self.close_btn.clicked.connect(viewer.close_viewer)

    def set_image(
        self, name: str, meta: str, index: int, total: int, has_prev: bool, has_next: bool
    ) -> None:
        self.name.set_full_text(name)
        self.meta.set_full_text(meta)
        self.counter.setText(f"{index + 1} / {total}")
        self.prev_btn.setEnabled(has_prev)
        self.next_btn.setEnabled(has_next)

    def set_zoom(self, percent: int, at_fit: bool) -> None:
        self.zoom_btn.setText("Fit" if at_fit else f"{percent}%")


# ---------------------------------------------------------------------------
# viewer
# ---------------------------------------------------------------------------


class Lightbox(QWidget):
    closed = pyqtSignal()

    def __init__(self, thumbs: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._thumbs = thumbs
        self._paths: list[str] = []
        self._index = -1
        self._appear = 0.0
        self._anim: QVariantAnimation | None = None
        self._closing = False
        self._chrome_visible = True
        self._cursor_hidden = False
        self._hud_anims: list[QPropertyAnimation] = []
        self._top_rect = QRect()
        self._film_rect = QRect()

        self.canvas = ImageCanvas(self)
        self.canvas.zoomChanged.connect(self._on_zoom)
        self.canvas.activity.connect(self._on_activity)
        self.canvas.imageLoaded.connect(self._refresh_info)

        self.top = TopBar(self)
        self.film = Filmstrip(thumbs, self)
        self.film.hide()

        self.film.goTo.connect(self.go_to)

        self._idle = QTimer(self)
        self._idle.setInterval(2800)
        self._idle.setSingleShot(False)
        self._idle.timeout.connect(self._maybe_hide_chrome)

        self._menu: QMenu | None = None

    # -- lifecycle ----------------------------------------------------------
    def open_at(self, paths: list[str], index: int) -> None:
        self._paths = list(paths)
        if not self._paths:
            return
        self._index = max(0, min(len(self._paths) - 1, index))
        self._closing = False
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.film.set_images(self._paths, self._index)
        self._load_current()
        self._show_chrome()
        self._animate_appear(1.0, 260)

    def close_viewer(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._idle.stop()
        self._show_chrome()
        self._animate_appear(0.0, 180, on_done=self._finish_close)

    def _finish_close(self) -> None:
        self._idle.stop()
        self._closing = False
        self.hide()
        self.canvas.release()  # give the decoded photos' memory back
        self._set_cursor_hidden(False)
        self.closed.emit()

    def _animate_appear(self, target: float, duration: int, on_done=None) -> None:
        if self._anim is not None:
            self._anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(duration)
        anim.setStartValue(self._appear)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._set_appear)
        if on_done is not None:
            anim.finished.connect(on_done)
        self._anim = anim
        anim.start()

    def _set_appear(self, value) -> None:
        self._appear = float(value)
        self.canvas.set_appear(self._appear)
        self.update()

    # -- navigation ---------------------------------------------------------
    def _load_current(self, forward: bool = True) -> None:
        if not self._paths:
            return
        path = self._paths[self._index]
        # Decode the photos you are most likely to look at next, in the
        # direction you are travelling, while this one is on screen.
        step = 1 if forward else -1
        ahead = [self._index + step, self._index - step, self._index + 2 * step]
        neighbours = [self._paths[i] for i in ahead if 0 <= i < len(self._paths)]
        self.canvas.set_image(path, self._thumbs.any_cached(path), neighbours)
        self._refresh_info()
        self.film.set_index(self._index)
        if len(self._paths) <= 1 and self.film.isVisible():
            self.film.hide()
        self._on_zoom(self.canvas.zoom_percent())

    def _refresh_info(self, *_args) -> None:
        """Title bar text for the current photo (re-run when loading finishes)."""
        if not 0 <= self._index < len(self._paths):
            return
        path = self._paths[self._index]
        state = self.canvas.state()
        if state == "failed":
            meta = "Unable to load this image"
        elif state == "ready":
            meta = _metadata(path, self.canvas.source_size())
        else:
            meta = _metadata(path, (0, 0))
        self.top.set_image(
            os.path.basename(path),
            meta,
            self._index,
            len(self._paths),
            self._index > 0,
            self._index < len(self._paths) - 1,
        )

    def go_to(self, index: int) -> None:
        if not self._paths:
            return
        index = max(0, min(len(self._paths) - 1, index))
        if index == self._index:
            return
        forward = index >= self._index
        self._index = index
        self._load_current(forward)
        self._show_chrome()

    def next_image(self) -> None:
        if self._index < len(self._paths) - 1:
            self.go_to(self._index + 1)

    def prev_image(self) -> None:
        if self._index > 0:
            self.go_to(self._index - 1)

    # -- zoom ---------------------------------------------------------------
    def zoom_in(self) -> None:
        self.canvas.zoom_by(1.25)
        self._show_chrome()

    def zoom_out(self) -> None:
        self.canvas.zoom_by(1 / 1.25)
        self._show_chrome()

    def fit(self) -> None:
        self.canvas.fit()
        self._show_chrome()

    def actual_size(self) -> None:
        self.canvas.actual_size()
        self._show_chrome()

    def _on_zoom(self, percent: int) -> None:
        at_fit = abs(getattr(self.canvas, "_zoom", 1.0) - 1.0) < 1e-6
        self.top.set_zoom(percent, at_fit)

    def zoom_menu(self, global_pos: QPoint) -> None:
        menu = make_menu(self)
        add_action(menu, "Fit to window", self.fit)
        add_action(menu, "Actual size (100%)", self.actual_size)
        menu.addSeparator()
        for value in (50, 100, 200, 400):
            add_action(
                menu,
                f"{value}%",
                lambda _=False, v=value: self.canvas.set_zoom_percent(v),
            )
        self._exec_menu(menu, global_pos)

    # -- menus --------------------------------------------------------------
    def action_menu(self, global_pos: QPoint) -> None:
        menu = make_menu(self)
        add_action(menu, "Fit to window", self.fit)
        add_action(menu, "Actual size", self.actual_size)
        menu.addSeparator()
        add_action(menu, "Copy file path", self._copy_path)
        add_action(menu, "Show in Explorer", self._reveal)
        menu.addSeparator()
        add_action(menu, "Close viewer", self.close_viewer)
        self._exec_menu(menu, global_pos)

    def _exec_menu(self, menu: QMenu, global_pos: QPoint) -> None:
        self._menu = menu
        self._idle.stop()
        menu.exec(global_pos)
        self._menu = None
        self._show_chrome()

    def _copy_path(self) -> None:
        if 0 <= self._index < len(self._paths):
            QApplication.clipboard().setText(self._paths[self._index])

    def _reveal(self) -> None:
        if 0 <= self._index < len(self._paths):
            native.reveal_in_explorer(self._paths[self._index])

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.action_menu(event.globalPos())

    # -- chrome auto-hide ---------------------------------------------------
    def _on_activity(self) -> None:
        self._show_chrome()

    def _show_chrome(self) -> None:
        if self._closing and self._appear < 0.05:
            return
        self._chrome_visible = True
        self._stop_hud_anims()
        for widget, rect in self._hud_targets():
            if rect.isNull():
                continue
            offset = -16 if widget is self.top else 18
            if not widget.isVisible():
                widget.move(rect.x(), rect.y() + offset)
                widget.show()
            widget.raise_()
            self._slide(widget, rect.topLeft(), 190)
        self._set_cursor_hidden(False)
        if not self._closing:
            self._idle.start()

    def _hud_targets(self) -> list[tuple[QWidget, QRect]]:
        targets: list[tuple[QWidget, QRect]] = [(self.top, self._top_rect)]
        if 0 <= self._index < len(self._paths) and len(self._paths) > 1:
            targets.append((self.film, self._film_rect))
        return targets

    def _maybe_hide_chrome(self) -> None:
        if not self._chrome_visible or self._closing:
            return
        if self._menu is not None and self._menu.isVisible():
            return
        pos = self.mapFromGlobal(QCursor.pos())
        if self.top.geometry().contains(pos):
            return
        if self.film.isVisible() and self.film.geometry().contains(pos):
            return
        if self.canvas._dragging:  # noqa: SLF001
            return
        self._chrome_visible = False
        self._stop_hud_anims()
        for widget, rect in self._hud_targets():
            if not widget.isVisible():
                continue
            offset = -12 if widget is self.top else 14
            self._slide(
                widget, QPoint(rect.x(), rect.y() + offset), 180, then_hide=True
            )
        self._set_cursor_hidden(True)

    def _stop_hud_anims(self) -> None:
        for anim in self._hud_anims:
            anim.stop()
        self._hud_anims.clear()

    def _slide(
        self, widget: QWidget, target: QPoint, duration: int, then_hide: bool = False
    ) -> None:
        anim = QPropertyAnimation(widget, b"pos", self)
        anim.setDuration(duration)
        anim.setStartValue(widget.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if then_hide:
            anim.finished.connect(widget.hide)
        self._hud_anims.append(anim)
        anim.start()

    def _set_cursor_hidden(self, hidden: bool) -> None:
        self._cursor_hidden = hidden
        self.canvas._set_cursor_hidden(hidden)  # noqa: SLF001
        if hidden:
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # -- events -------------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        width, height = self.width(), self.height()
        self.canvas.setGeometry(0, 0, width, height)
        margin = 24
        self._top_rect = QRect(margin, margin, max(320, width - margin * 2), 58)
        film_width = max(320, min(width - margin * 2, 1000))
        self._film_rect = QRect(
            (width - film_width) // 2, height - 84 - margin, film_width, 84
        )
        self.top.resize(self._top_rect.size())
        self.film.resize(self._film_rect.size())
        if self._chrome_visible:
            self.top.move(self._top_rect.topLeft())
            if self.film.isVisible():
                self.film.move(self._film_rect.topLeft())
        else:
            self.top.move(self._top_rect.x(), self._top_rect.y() - 12)
            self.film.move(self._film_rect.x(), self._film_rect.y() + 14)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._appear <= 0.001:
            return
        p = QPainter(self)
        p.fillRect(
            self.rect(), QColor(0, 0, 0, int(round(VEIL_ALPHA * self._appear)))
        )
        p.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._show_chrome()
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_viewer()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space,
                     Qt.Key.Key_PageDown):
            self.next_image()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.prev_image()
        elif key == Qt.Key.Key_Home:
            self.go_to(0)
        elif key == Qt.Key.Key_End:
            self.go_to(len(self._paths) - 1)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif key == Qt.Key.Key_Minus:
            self.zoom_out()
        elif key == Qt.Key.Key_0:
            self.fit()
        elif key == Qt.Key.Key_1:
            self.actual_size()
        else:
            self._show_chrome()
            super().keyPressEvent(event)
