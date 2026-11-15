"""Thumbnail gallery: a virtualised card grid, hover-animated cards and the empty state.

The grid is a single scroll area that *paints* the cards that are on screen
instead of owning one widget per image.  A folder of 5 000 photos therefore
costs the same to open, lay out and scroll as a folder of 50, and thumbnails
are only decoded for the cards the user can actually see (plus a little
look-ahead).
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import formats
from .icons import LogoMark, PillButton, draw_icon, mix
from .theme import ACCENT
from .thumbs import ThumbnailService

CARD_SIZES = {"compact": 168, "comfortable": 214, "large": 272}

GAP = 18
MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM = 26, 22, 20, 30
RADIUS = 13.0
HOVER_SECONDS = 0.17
BAKED_LIMIT = 220
OWNER = "gallery"


def _cover_source(pixmap: QPixmap, rect: QRectF) -> QRectF:
    iw, ih = pixmap.width(), pixmap.height()
    if iw <= 0 or ih <= 0:
        return QRectF()
    target_ratio = rect.width() / max(1.0, rect.height())
    source_ratio = iw / ih
    if source_ratio > target_ratio:
        new_w = ih * target_ratio
        return QRectF((iw - new_w) / 2.0, 0, new_w, ih)
    new_h = iw / target_ratio
    return QRectF(0, (ih - new_h) / 2.0, iw, new_h)


class EmptyState(QWidget):
    open_folder = pyqtSignal()
    open_image = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(0)
        layout.addStretch(1)

        layout.addWidget(LogoMark(58), 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(18)

        title = QLabel("A quiet place for your pictures")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(8)

        body = QLabel(
            "Drop images anywhere in this window, or open a folder to browse a collection."
        )
        body.setObjectName("emptyBody")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addSpacing(22)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        primary = PillButton(
            "Open folder", icon="folder", variant="accent", height=36, radius=10
        )
        primary.clicked.connect(self.open_folder.emit)
        secondary = PillButton("Open image", icon="image", height=36, radius=10)
        secondary.clicked.connect(self.open_image.emit)
        row.addWidget(primary)
        row.addWidget(secondary)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addSpacing(18)
        hint = QLabel(formats.hint())
        hint.setObjectName("emptyHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(1)


class CardGrid(QAbstractScrollArea):
    """Virtualised, left-aligned grid of square thumbnail cards."""

    activated = pyqtSignal(str)

    def __init__(self, thumbs: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thumbs = thumbs
        self._paths: list[str] = []
        self._index: dict[str, int] = {}
        self._size = CARD_SIZES["comfortable"]
        self._cols = 1

        # Pre-rendered card faces (thumbnail + rounded corners + caption).
        self._baked: "OrderedDict[tuple[str, int, float], QPixmap]" = OrderedDict()
        self._placeholder: tuple[tuple[int, float], QPixmap] | None = None

        self._hover_idx = -1
        self._pressed_idx = -1
        self._hover_value: dict[int, float] = {}
        self._hover_target: dict[int, float] = {}
        self._hover_clock = 0.0
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(16)
        self._hover_timer.timeout.connect(self._tick_hover)

        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(16)
        self._request_timer.timeout.connect(self._request_visible)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalScrollBar().setSingleStep(20)
        viewport = self.viewport()
        viewport.setAutoFillBackground(False)
        viewport.setMouseTracking(True)

        thumbs.ready.connect(self._on_thumb)

    # -- content ------------------------------------------------------------
    def set_paths(self, paths: list[str], *, keep_scroll: bool = False) -> None:
        previous = self.verticalScrollBar().value()
        self._paths = list(paths)
        self._index = {path: i for i, path in enumerate(self._paths)}
        self._baked.clear()
        self._hover_idx = self._pressed_idx = -1
        self._hover_value.clear()
        self._hover_target.clear()
        self._hover_timer.stop()
        self._thumbs.set_wanted(OWNER, ())
        self._relayout()
        self.verticalScrollBar().setValue(previous if keep_scroll else 0)
        self.viewport().update()
        self._request_visible()

    def clear(self) -> None:
        self.set_paths([])

    def count(self) -> int:
        return len(self._paths)

    def card_size(self) -> int:
        return self._size

    def set_card_size(self, size: int) -> None:
        if size == self._size:
            return
        anchor = self._first_visible_index()
        self._size = size
        self._baked.clear()
        self._placeholder = None
        self._relayout()
        self._scroll_to_index(anchor)
        self.viewport().update()
        self._request_visible()

    # -- geometry -----------------------------------------------------------
    def _decode_px(self) -> int:
        dpr = max(1.0, self.viewport().devicePixelRatioF())
        return max(64, int(round(self._size * dpr)))

    def _relayout(self) -> None:
        viewport = self.viewport()
        avail = max(1, viewport.width() - MARGIN_LEFT - MARGIN_RIGHT)
        self._cols = max(1, (avail + GAP) // (self._size + GAP))
        rows = -(-len(self._paths) // self._cols) if self._paths else 0
        content = 0
        if rows:
            content = (
                MARGIN_TOP
                + MARGIN_BOTTOM
                + rows * self._size
                + (rows - 1) * GAP
            )
        bar = self.verticalScrollBar()
        bar.setPageStep(viewport.height())
        bar.setRange(0, max(0, content - viewport.height()))

    def _card_rect(self, index: int) -> QRect:
        row, col = divmod(index, self._cols)
        step = self._size + GAP
        return QRect(
            MARGIN_LEFT + col * step,
            MARGIN_TOP + row * step - self.verticalScrollBar().value(),
            self._size,
            self._size,
        )

    def _index_range(self, top: int, bottom: int) -> tuple[int, int]:
        """Card indices whose rows touch viewport y in [top, bottom]."""
        if not self._paths:
            return 0, 0
        step = self._size + GAP
        offset = self.verticalScrollBar().value() - MARGIN_TOP
        first_row = max(0, (top + offset) // step)
        last_row = max(first_row, (bottom + offset) // step)
        return (
            min(len(self._paths), first_row * self._cols),
            min(len(self._paths), (last_row + 1) * self._cols),
        )

    def _first_visible_index(self) -> int:
        first, _ = self._index_range(0, 0)
        return first

    def _scroll_to_index(self, index: int) -> None:
        row = index // max(1, self._cols)
        self.verticalScrollBar().setValue(max(0, row * (self._size + GAP)))

    def _hit(self, pos: QPoint) -> int:
        step = self._size + GAP
        x = pos.x() - MARGIN_LEFT
        y = pos.y() + self.verticalScrollBar().value() - MARGIN_TOP
        if x < 0 or y < 0:
            return -1
        col, dx = divmod(x, step)
        row, dy = divmod(y, step)
        if dx >= self._size or dy >= self._size or col >= self._cols:
            return -1
        index = row * self._cols + col
        return index if index < len(self._paths) else -1

    # -- thumbnails ---------------------------------------------------------
    def _request_visible(self) -> None:
        if not self._paths:
            self._thumbs.set_wanted(OWNER, ())
            return
        height = self.viewport().height()
        vis_first, vis_last = self._index_range(0, height)
        buf_first, buf_last = self._index_range(-height // 2, height + height // 2)
        px = self._decode_px()
        paths = self._paths
        self._thumbs.set_wanted(
            OWNER, ((paths[i], px) for i in range(buf_first, buf_last))
        )
        # The pool serves the newest request first, so queue the least
        # important cards first: look-ahead, then the visible ones top-left
        # last (= decoded first).
        order = (
            list(range(vis_last, buf_last))[::-1]
            + list(range(buf_first, vis_first))[::-1]
            + list(range(vis_first, vis_last))[::-1]
        )
        for i in order:
            self._thumbs.request(paths[i], px, OWNER)

    def _schedule_request(self) -> None:
        if not self._request_timer.isActive():
            self._request_timer.start()

    def _on_thumb(self, path: str, px: int, pixmap: QPixmap) -> None:
        index = self._index.get(path)
        if index is None or px != self._decode_px():
            return
        self._baked.pop((path, self._size, self.viewport().devicePixelRatioF()), None)
        rect = self._card_rect(index).adjusted(-4, -4, 4, 4)
        if rect.intersects(self.viewport().rect()):
            self.viewport().update(rect)

    # -- card faces ---------------------------------------------------------
    def _make_face(self, dpr: float) -> tuple[QPixmap, QPainter, QRectF, QPainterPath]:
        side = self._size
        pm = QPixmap(round(side * dpr), round(side * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        frame = QRectF(0, 0, side, side).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(frame, RADIUS, RADIUS)
        return pm, p, frame, path

    def _placeholder_face(self, dpr: float) -> QPixmap:
        key = (self._size, dpr)
        if self._placeholder is not None and self._placeholder[0] == key:
            return self._placeholder[1]
        pm, p, frame, path = self._make_face(dpr)
        p.setClipPath(path)
        grad = QLinearGradient(frame.topLeft(), frame.bottomRight())
        grad.setColorAt(0.0, QColor("#181C26"))
        grad.setColorAt(1.0, QColor("#101219"))
        p.fillPath(path, grad)
        dot = QRectF(frame.center().x() - 13, frame.center().y() - 17, 26, 26)
        draw_icon(p, "image", dot, QColor(255, 255, 255, 46), 1.4)
        self._add_caption_veil(p, frame)
        p.end()
        self._placeholder = (key, pm)
        return pm

    @staticmethod
    def _add_caption_veil(p: QPainter, frame: QRectF) -> None:
        veil = QLinearGradient(0, frame.height() * 0.55, 0, frame.height())
        veil.setColorAt(0.0, QColor(0, 0, 0, 0))
        veil.setColorAt(1.0, QColor(0, 0, 0, 180))
        p.fillRect(
            QRectF(0, frame.height() * 0.55, frame.width(), frame.height() * 0.45),
            veil,
        )

    def _bake(self, path: str, dpr: float) -> QPixmap | None:
        thumb = self._thumbs.cached(path, self._decode_px())
        if thumb is None or thumb.isNull():
            return None
        pm, p, frame, clip = self._make_face(dpr)
        p.save()
        p.setClipPath(clip)
        p.fillPath(clip, QColor("#151821"))
        p.drawPixmap(frame, thumb, _cover_source(thumb, frame))
        self._add_caption_veil(p, frame)
        p.restore()

        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(QColor(240, 243, 250, 225))
        text_rect = frame.adjusted(11, 0, -11, -8)
        text = p.fontMetrics().elidedText(
            os.path.basename(path), Qt.TextElideMode.ElideMiddle, int(text_rect.width())
        )
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            text,
        )
        p.end()
        return pm

    def _face(self, path: str, dpr: float) -> QPixmap:
        key = (path, self._size, dpr)
        face = self._baked.get(key)
        if face is not None:
            self._baked.move_to_end(key)
            return face
        face = self._bake(path, dpr)
        if face is None:
            return self._placeholder_face(dpr)
        self._baked[key] = face
        while len(self._baked) > BAKED_LIMIT:
            self._baked.popitem(last=False)
        return face

    # -- hover --------------------------------------------------------------
    def _set_hover_index(self, index: int) -> None:
        if index == self._hover_idx:
            return
        if self._hover_idx >= 0:
            self._hover_target[self._hover_idx] = 0.0
        self._hover_idx = index
        if index >= 0:
            self._hover_target[index] = 1.0
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()
        if self._hover_target and not self._hover_timer.isActive():
            self._hover_clock = time.perf_counter()
            self._hover_timer.start()

    def _tick_hover(self) -> None:
        now = time.perf_counter()
        step = (now - self._hover_clock) / HOVER_SECONDS
        self._hover_clock = now
        moving = False
        for index in list(self._hover_target):
            target = self._hover_target[index]
            value = self._hover_value.get(index, 0.0)
            value = min(target, value + step) if target > value else max(target, value - step)
            self.viewport().update(self._card_rect(index).adjusted(-4, -4, 4, 4))
            if value == target:
                if target == 0.0:
                    self._hover_target.pop(index, None)
                    self._hover_value.pop(index, None)
                    continue
                self._hover_value[index] = value
            else:
                self._hover_value[index] = value
                moving = True
        if not moving:
            self._hover_timer.stop()

    # -- events -------------------------------------------------------------
    def viewportEvent(self, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.Leave:
            self._set_hover_index(-1)
        elif kind == QEvent.Type.ToolTip:
            index = self._hit(event.pos())
            if index >= 0:
                QToolTip.showText(
                    event.globalPos(), os.path.basename(self._paths[index]), self.viewport()
                )
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().viewportEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._set_hover_index(self._hit(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._hit(event.position().toPoint())
            self._pressed_idx = index
            if index >= 0:
                self.viewport().update(self._card_rect(index))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        pressed, self._pressed_idx = self._pressed_idx, -1
        if pressed >= 0:
            self.viewport().update(self._card_rect(pressed))
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._hit(event.position().toPoint()) == pressed
            ):
                self.activated.emit(self._paths[pressed])
        super().mouseReleaseEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        self.viewport().scroll(dx, dy)
        self._schedule_request()
        if self._hover_idx >= 0 or self._pressed_idx < 0:
            pos = self.viewport().mapFromGlobal(QCursor.pos())
            if self.viewport().rect().contains(pos):
                self._set_hover_index(self._hit(pos))

    def resizeEvent(self, event) -> None:  # noqa: N802
        anchor = self._first_visible_index()
        super().resizeEvent(event)
        self._relayout()
        self._scroll_to_index(anchor)
        self._schedule_request()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._relayout()
        self._schedule_request()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._paths:
            return
        dirty = event.rect()
        first, last = self._index_range(dirty.top(), dirty.bottom())
        dpr = self.viewport().devicePixelRatioF()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for index in range(first, last):
            rect = self._card_rect(index)
            if not rect.intersects(dirty):
                continue
            face = self._face(self._paths[index], dpr)
            t = self._hover_value.get(index, 0.0)
            t = 1.0 - (1.0 - t) ** 3  # ease-out

            frame = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
            if t > 0.004:
                grow = 1.0 + 0.022 * t
                target = QRectF(
                    frame.center().x() - frame.width() * grow / 2,
                    frame.center().y() - frame.height() * grow / 2,
                    frame.width() * grow,
                    frame.height() * grow,
                )
                clip = QPainterPath()
                clip.addRoundedRect(frame, RADIUS, RADIUS)
                p.save()
                p.setClipPath(clip)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawPixmap(target, face, QRectF(face.rect()))
                p.restore()
            else:
                p.drawPixmap(rect.topLeft(), face)

            if index == self._pressed_idx:
                shade = QPainterPath()
                shade.addRoundedRect(frame, RADIUS, RADIUS)
                p.fillPath(shade, QColor(0, 0, 0, 46))

            stroke = mix(QColor(255, 255, 255, 24), QColor(ACCENT), t)
            stroke.setAlpha(int(24 + (150 - 24) * t))
            pen = QPen(stroke)
            pen.setWidthF(1.0 + 0.5 * t)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                frame.adjusted(0.4, 0.4, -0.4, -0.4), RADIUS - 0.4, RADIUS - 0.4
            )
        p.end()


class GalleryView(QWidget):
    activated = pyqtSignal(str)
    open_folder_requested = pyqtSignal()
    open_image_requested = pyqtSignal()

    def __init__(self, thumbs: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thumbs = thumbs

        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("background: transparent;")

        self.empty = EmptyState(self)
        self._stack.addWidget(self.empty)

        self.scroll = CardGrid(thumbs, self)
        self.scroll.activated.connect(self.activated.emit)
        self._stack.addWidget(self.scroll)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self.empty.open_folder.connect(self.open_folder_requested.emit)
        self.empty.open_image.connect(self.open_image_requested.emit)

    # -- content ------------------------------------------------------------
    def set_paths(self, paths: list[str], *, keep_scroll: bool = False) -> None:
        # Switch pages first so the grid is laid out at its real size.
        self._stack.setCurrentWidget(self.scroll if paths else self.empty)
        self.scroll.set_paths(paths, keep_scroll=keep_scroll)

    def clear(self) -> None:
        self.scroll.clear()

    def card_size(self) -> int:
        return self.scroll.card_size()

    def set_card_size(self, size: int) -> None:
        self.scroll.set_card_size(size)

    def count(self) -> int:
        return self.scroll.count()
