"""Shared chrome widgets: dividers, wordmark, menus, drop overlay, about box."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .icons import LogoMark, PillButton, make_app_icon
from .theme import ACCENT, ACCENT_BRIGHT, INK, SURFACE, TEXT, TEXT_DIM, TEXT_FAINT


class ElideLabel(QLabel):
    """QLabel that stores the full text and elides it to the available width."""

    def __init__(
        self,
        text: str = "",
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self._refresh()

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        width = max(0, self.width() - 2)
        self.setText(self.fontMetrics().elidedText(self._full, self._mode, width))


class Divider(QFrame):
    def __init__(self, vertical: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("vsep" if vertical else "hsep")
        if vertical:
            self.setFixedSize(1, 16)
        else:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class DropOverlay(QWidget):
    """Rounded, dashed highlight shown while dragging files over the window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(14, 14, -14, -14)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(8, 9, 12, 225))
        p.drawRoundedRect(rect, 16, 16)

        pen = QPen(QColor(ACCENT), 1.6, Qt.PenStyle.DashLine)
        pen.setDashPattern([5.0, 4.0])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 16, 16)

        font = QFont(self.font())
        font.setPixelSize(16)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(TEXT))
        p.drawText(
            rect.adjusted(0, -14, 0, -14),
            Qt.AlignmentFlag.AlignCenter,
            "Drop to open",
        )

        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor(TEXT_DIM))
        p.drawText(
            rect.adjusted(0, 22, 0, 22),
            Qt.AlignmentFlag.AlignCenter,
            "images, or a folder of images",
        )
        p.end()


def make_menu(parent: QWidget | None = None) -> QMenu:
    menu = QMenu(parent)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    menu.ensurePolished()
    return menu


def add_action(
    menu: QMenu,
    text: str,
    slot=None,
    *,
    shortcut: str | None = None,
    enabled: bool = True,
    check: bool = False,
) -> QAction:
    action = QAction(text, menu)
    action.setEnabled(enabled)
    if shortcut:
        action.setShortcut(shortcut)
        action.setShortcutVisibleInContextMenu(True)
    if check:
        action.setCheckable(True)
        action.setChecked(True)
    if slot is not None:
        action.triggered.connect(slot)
    menu.addAction(action)
    return action


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Lumina")
        self.setWindowIcon(make_app_icon())
        self.setFixedWidth(370)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(0)

        mark = LogoMark(52)
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(14)

        title = QLabel("Lumina")
        font = QFont(title.font())
        font.setPixelSize(20)
        font.setWeight(QFont.Weight.DemiBold)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel(f"Version {__version__}")
        version.setStyleSheet(f"color: {TEXT_FAINT}; font-size: 11px;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        layout.addSpacing(14)

        blurb = QLabel(
            "A quiet place for your pictures.\n"
            "Full-screen viewing over a translucent glass veil, "
            "with drag, drop and keyboard navigation."
        )
        blurb.setWordWrap(True)
        blurb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        blurb.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px; line-height: 150%;")
        layout.addWidget(blurb)
        layout.addSpacing(20)

        close = PillButton("Close", variant="accent", height=34, parent=self)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        row.addStretch(1)
        layout.addLayout(row)

        self.setStyleSheet(
            f"QDialog {{ background-color: {SURFACE}; border: 1px solid rgba(255,255,255,20); }}"
        )
