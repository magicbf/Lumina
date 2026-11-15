"""The branded Lumina installer / uninstaller window.

Everything is painted with QPainter from the same logo and palette as the app,
so Setup looks like part of Lumina rather than a generic wizard.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import time
import winreg
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QThread,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, native
from ..icons import IconButton, PillButton, make_app_icon, mix
from ..theme import (
    ACCENT,
    INK,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
    base_qss,
    pick_ui_font,
)
from . import ops

WIDTH, HEIGHT = 820, 540
LEFT_W = 278
RADIUS = 18.0
LOGO_A, LOGO_B = QColor("#93ACFF"), QColor("#A489FF")  # the lens mark's gradient

PAGE_OPTIONS, PAGE_PROGRESS, PAGE_DONE, PAGE_ERROR = range(4)


# ---------------------------------------------------------------------------
# small painted widgets
# ---------------------------------------------------------------------------


class CheckRow(QAbstractButton):
    """A card-style tick option: custom check box, title and one-line hint."""

    def __init__(self, title: str, hint: str, checked: bool = True) -> None:
        super().__init__()
        self._title, self._hint = title, hint
        self._hover = 0.0
        self._t = 1.0 if checked else 0.0
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._check_anim = self._make_anim(self._set_t)
        self._hover_anim = self._make_anim(self._set_hover)
        self.toggled.connect(lambda on: self._run(self._check_anim, self._t, 1.0 if on else 0.0))

    def _make_anim(self, setter: Callable[[float], None]) -> QVariantAnimation:
        anim = QVariantAnimation(self)
        anim.setDuration(170)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: setter(float(v)))
        return anim

    @staticmethod
    def _run(anim: QVariantAnimation, start: float, end: float) -> None:
        anim.stop()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def _set_t(self, value: float) -> None:
        self._t = value
        self.update()

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._run(self._hover_anim, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._run(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        h, t = self._hover, self._t

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(9 + 9 * h)))
        p.drawRoundedRect(card, 12, 12)
        border = mix(QColor(255, 255, 255, 22), LOGO_A, 0.55 * t)
        border.setAlpha(int(22 + 60 * t + 18 * h))
        p.setPen(QPen(border, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card, 12, 12)

        box = QRectF(16, (self.height() - 22) / 2, 22, 22)
        p.setPen(QPen(QColor(255, 255, 255, int(70 * (1 - t) + 20)), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if t < 1.0:
            p.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 7, 7)
        if t > 0.0:
            grad = QLinearGradient(box.topLeft(), box.bottomRight())
            a, b = QColor(LOGO_A), QColor(LOGO_B)
            a.setAlphaF(t)
            b.setAlphaF(t)
            grad.setColorAt(0.0, a)
            grad.setColorAt(1.0, b)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(box, 7, 7)
            pen = QPen(QColor(INK), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            _draw_check(p, box.adjusted(5, 5, -5, -5), t)

        x = 52
        width = self.width() - x - 16
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(x, 9, width, 18), Qt.AlignmentFlag.AlignVCenter, self._title)
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor(TEXT_FAINT))
        hint = QFontMetrics(font).elidedText(self._hint, Qt.TextElideMode.ElideRight, int(width))
        p.drawText(QRectF(x, 28, width, 16), Qt.AlignmentFlag.AlignVCenter, hint)
        p.end()


def _draw_check(p: QPainter, box: QRectF, progress: float) -> None:
    """A tick mark that draws itself as *progress* goes 0 -> 1."""
    pts = [
        QPointF(box.left(), box.center().y() + box.height() * 0.05),
        QPointF(box.left() + box.width() * 0.36, box.bottom() - box.height() * 0.05),
        QPointF(box.right(), box.top() + box.height() * 0.05),
    ]
    first = math.dist((pts[0].x(), pts[0].y()), (pts[1].x(), pts[1].y()))
    second = math.dist((pts[1].x(), pts[1].y()), (pts[2].x(), pts[2].y()))
    reach = max(0.0, min(1.0, progress)) * (first + second)
    path = QPainterPath(pts[0])
    if reach <= first:
        f = reach / first
        path.lineTo(pts[0] + (pts[1] - pts[0]) * f)
    else:
        path.lineTo(pts[1])
        f = (reach - first) / second
        path.lineTo(pts[1] + (pts[2] - pts[1]) * f)
    p.drawPath(path)


class GlowBar(QWidget):
    """Smoothly animated progress bar with a moving highlight."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(12)
        self._target = 0.0
        self._shown = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_value(self, value: float) -> None:
        self._target = max(0.0, min(1.0, value))

    def shown_value(self) -> float:
        return self._shown

    def _tick(self) -> None:
        self._shown += (self._target - self._shown) * 0.12
        if abs(self._target - self._shown) < 0.0015:
            self._shown = self._target
        self._phase = (self._phase + 0.018) % 1.0
        if self.isVisible():
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        width = max(track.height(), track.width() * self._shown)
        fill = QRectF(track.left(), track.top(), width, track.height())
        grad = QLinearGradient(track.left(), 0, track.right(), 0)
        grad.setColorAt(0.0, LOGO_A)
        grad.setColorAt(1.0, LOGO_B)
        p.setBrush(grad)
        p.drawRoundedRect(fill, track.height() / 2, track.height() / 2)
        if self._shown < 0.999:
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(fill, track.height() / 2, track.height() / 2)
            p.setClipPath(clip)
            x = fill.left() + (fill.width() + 80) * self._phase - 80
            shine = QLinearGradient(x, 0, x + 80, 0)
            shine.setColorAt(0.0, QColor(255, 255, 255, 0))
            shine.setColorAt(0.5, QColor(255, 255, 255, 80))
            shine.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(fill, shine)
            p.restore()
        p.end()


class CheckBadge(QWidget):
    """A ring and tick that draw themselves once, for the finished page."""

    def __init__(self, size: int = 104) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._p = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(900)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set)

    def play(self) -> None:
        self._anim.stop()
        self._anim.start()

    def _set(self, value) -> None:
        self._p = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        glow = QRadialGradient(rect.center(), rect.width() * 0.7)
        glow.setColorAt(0.0, QColor(147, 172, 255, int(70 * self._p)))
        glow.setColorAt(1.0, QColor(147, 172, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(self.rect()))

        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, LOGO_A)
        grad.setColorAt(1.0, LOGO_B)
        pen = QPen(grad, 4.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        sweep = int(360 * 16 * min(1.0, self._p / 0.6))
        p.drawArc(rect, 90 * 16, -sweep)

        tick = max(0.0, (self._p - 0.5) / 0.5)
        if tick > 0:
            _draw_check(p, rect.adjusted(rect.width() * 0.27, rect.height() * 0.3,
                                         -rect.width() * 0.25, -rect.height() * 0.28), tick)
        p.end()


# ---------------------------------------------------------------------------
# background worker
# ---------------------------------------------------------------------------


class Worker(QThread):
    progressed = pyqtSignal(float, str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job: Callable[[Callable[[float, str], None]], object]) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:  # noqa: D401
        try:
            result = self._job(lambda f, t: self.progressed.emit(f, t))
        except ops.SetupError as error:
            self.failed.emit(str(error))
        except Exception as error:  # pragma: no cover - last resort
            self.failed.emit(f"Something went wrong:\n{error}")
        else:
            self.succeeded.emit(result)


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------


def _label(text: str, size: int, colour: str, weight: int = 400, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(wrap)
    label.setStyleSheet(
        f"color: {colour}; font-size: {size}px; font-weight: {weight}; background: transparent;"
    )
    return label


FIELD_QSS = f"""
QLineEdit {{
    background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,30);
    border-radius: 10px; padding: 0 12px; color: {TEXT}; font-size: 12px;
    selection-background-color: rgba(124,156,255,120);
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
"""


class Wizard(QWidget):
    def __init__(self, uninstall: bool = False, install_dir: Path | None = None) -> None:
        super().__init__()
        self._uninstall = uninstall
        self._dir = install_dir
        self._worker: Worker | None = None
        self._busy = False
        self._exe: Path | None = None
        self._associate = False
        self._phase = 0.0
        self._step = 0
        self._removal_dir: Path | None = None

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(WIDTH, HEIGHT)
        self.setWindowTitle("Lumina Uninstall" if uninstall else "Lumina Setup")
        self.setWindowIcon(make_app_icon())
        self._logo = make_app_icon(256).pixmap(168, 168)

        self.stack = QStackedWidget(self)
        self.stack.setGeometry(LEFT_W, 0, WIDTH - LEFT_W, HEIGHT)
        self.stack.addWidget(self._build_options())
        self.stack.addWidget(self._build_progress())
        self.stack.addWidget(self._build_done())
        self.stack.addWidget(self._build_error())

        self.close_btn = IconButton("close", size=32, radius=9, danger=True, tooltip="Close")
        self.close_btn.setParent(self)
        self.close_btn.move(WIDTH - 44, 12)
        self.close_btn.clicked.connect(self.close)
        self.close_btn.raise_()

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start()

    # -- pages ---------------------------------------------------------------
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(44, 46, 44, 30)
        layout.setSpacing(0)
        return page, layout

    def _build_options(self) -> QWidget:
        page, lay = self._page()
        if self._uninstall:
            lay.addWidget(_label("Remove Lumina?", 26, "#F4F6FC", 600))
            lay.addSpacing(8)
            lay.addWidget(
                _label(
                    "This takes Lumina off your PC: the app, its shortcuts and its entries "
                    "in Windows. Your pictures are never touched.",
                    13,
                    TEXT_DIM,
                    wrap=True,
                )
            )
            lay.addSpacing(26)
            self.chk_settings = CheckRow(
                "Also delete my settings", "Sort order, thumbnail size, recent folders and logs", False
            )
            lay.addWidget(self.chk_settings)
            lay.addStretch(1)
            lay.addLayout(self._buttons("Cancel", "Uninstall", self.close, self._start))
            return page

        lay.addWidget(_label("Install Lumina", 26, "#F4F6FC", 600))
        lay.addSpacing(6)
        lay.addWidget(
            _label("A fast, quiet image viewer. Choose where it goes and how it fits in.", 13, TEXT_DIM, wrap=True)
        )
        lay.addSpacing(18)
        lay.addWidget(_label("Install location", 11, TEXT_FAINT, 600))
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(ops.default_dir())
        self.path_edit.setFixedHeight(38)
        self.path_edit.setStyleSheet(FIELD_QSS)
        browse = PillButton("Browse…", height=38, radius=10, pad=14)
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        lay.addLayout(row)
        lay.addSpacing(16)
        lay.addWidget(_label("Options", 11, TEXT_FAINT, 600))
        lay.addSpacing(6)
        self.chk_start = CheckRow("Start menu shortcut", "Find Lumina in the Start menu", True)
        self.chk_desktop = CheckRow("Desktop shortcut", "Put a Lumina icon on your desktop", True)
        self.chk_assoc = CheckRow(
            "Use Lumina for pictures",
            "Offer Lumina for JPG, PNG, WebP, HEIC and more in Windows",
            True,
        )
        for chk in (self.chk_start, self.chk_desktop, self.chk_assoc):
            lay.addWidget(chk)
            lay.addSpacing(6)
        lay.addStretch(1)

        size_mb = ops.payload_size() / (1024 * 1024)
        note = _label(f"Needs about {size_mb:.0f} MB" if size_mb else "", 11, TEXT_FAINT)
        buttons = self._buttons("Cancel", "Install", self.close, self._start)
        buttons.insertWidget(0, note)
        lay.addLayout(buttons)
        return page

    def _buttons(self, cancel: str, go: str, on_cancel, on_go) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        cancel_btn = PillButton(cancel, height=38, radius=11, pad=20)
        cancel_btn.clicked.connect(on_cancel)
        go_btn = PillButton(go, variant="accent", height=38, radius=11, pad=26)
        go_btn.clicked.connect(on_go)
        row.addWidget(cancel_btn)
        row.addWidget(go_btn)
        self._go_btn = go_btn
        return row

    def _build_progress(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(2)
        self.progress_title = _label("Removing Lumina" if self._uninstall else "Installing Lumina", 26, "#F4F6FC", 600)
        lay.addWidget(self.progress_title)
        lay.addSpacing(8)
        self.progress_text = _label("Preparing…", 13, TEXT_DIM)
        lay.addWidget(self.progress_text)
        lay.addSpacing(26)
        self.bar = GlowBar()
        lay.addWidget(self.bar)
        lay.addSpacing(10)
        self.percent = _label("0%", 11, TEXT_FAINT)
        lay.addWidget(self.percent)
        lay.addStretch(3)
        return page

    def _build_done(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(1)
        self.badge = CheckBadge()
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addSpacing(14)
        self.done_title = _label("Lumina is ready", 26, "#F4F6FC", 600)
        lay.addWidget(self.done_title)
        lay.addSpacing(8)
        self.done_text = _label("", 13, TEXT_DIM, wrap=True)
        lay.addWidget(self.done_text)
        lay.addSpacing(22)
        self.chk_launch = CheckRow("Open Lumina now", "Start the viewer when you finish", True)
        lay.addWidget(self.chk_launch)
        lay.addStretch(2)
        row = QHBoxLayout()
        row.addStretch(1)
        finish = PillButton("Finish", variant="accent", height=38, radius=11, pad=30)
        finish.clicked.connect(self._finish)
        row.addWidget(finish)
        lay.addLayout(row)
        return page

    def _build_error(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(1)
        lay.addWidget(_label("That didn't work", 26, "#FF8A8A", 600))
        lay.addSpacing(10)
        self.error_text = _label("", 13, TEXT_DIM, wrap=True)
        lay.addWidget(self.error_text)
        lay.addStretch(2)
        row = QHBoxLayout()
        row.addStretch(1)
        back = PillButton("Back", height=38, radius=11, pad=22)
        back.clicked.connect(lambda: self._show(PAGE_OPTIONS))
        close = PillButton("Close", variant="accent", height=38, radius=11, pad=26)
        close.clicked.connect(self.close)
        row.addWidget(back)
        row.addWidget(close)
        lay.addLayout(row)
        return page

    def _show(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self._step = {PAGE_OPTIONS: 0, PAGE_PROGRESS: 1, PAGE_DONE: 2, PAGE_ERROR: 1}[page]
        self.update()

    # -- actions -------------------------------------------------------------
    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Install Lumina to", self.path_edit.text())
        if folder:
            self.path_edit.setText(str(Path(folder) / "Lumina") if Path(folder).name.lower() != "lumina" else folder)

    def _start(self) -> None:
        if self._busy:
            return
        if self._uninstall:
            directory = self._dir or Path(ops.default_dir())
            remove_settings = self.chk_settings.isChecked()
            self._removal_dir = directory
            job = lambda cb: ops.uninstall(directory, remove_settings, cb)  # noqa: E731
        else:
            text = self.path_edit.text().strip().strip('"')
            if not text or not Path(text).expanduser().is_absolute():
                self.error_text.setText("Please enter a full folder path, like C:\\Users\\you\\Lumina.")
                self._show(PAGE_ERROR)
                return
            options = ops.InstallOptions(
                directory=text,
                start_menu=self.chk_start.isChecked(),
                desktop=self.chk_desktop.isChecked(),
                associate=self.chk_assoc.isChecked(),
            )
            self._associate = options.associate
            job = lambda cb: ops.install(options, cb)  # noqa: E731

        self._busy = True
        self.close_btn.setEnabled(False)
        self._show(PAGE_PROGRESS)
        self._worker = Worker(job)
        self._worker.progressed.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._started_at = time.perf_counter()
        self._worker.start()

    def _on_progress(self, fraction: float, text: str) -> None:
        self.bar.set_value(fraction)
        self.progress_text.setText(text)
        self.percent.setText(f"{int(fraction * 100)}%")

    def _on_success(self, result) -> None:
        # Let the bar visibly finish instead of snapping to the last page.
        self.bar.set_value(1.0)
        self._exe = result if isinstance(result, Path) else None

        def finish_up() -> None:
            if self.bar.shown_value() < 0.995:
                QTimer.singleShot(40, finish_up)
                return
            self._busy = False
            self.close_btn.setEnabled(True)
            if self._uninstall:
                self.done_title.setText("Lumina was removed")
                self.done_text.setText("Thanks for trying it. Your pictures were not touched.")
                self.chk_launch.hide()
            else:
                self.done_text.setText(
                    f"Installed to {self._exe.parent if self._exe else ''}.\n"
                    + (
                        "When you finish, Windows opens Default apps — choose Lumina "
                        "there to make it your picture viewer."
                        if self._associate
                        else ""
                    )
                )
            self._show(PAGE_DONE)
            self.badge.play()

        QTimer.singleShot(250, finish_up)

    def _on_failure(self, message: str) -> None:
        self._busy = False
        self.close_btn.setEnabled(True)
        self.error_text.setText(message)
        self._show(PAGE_ERROR)

    def _finish(self) -> None:
        if not self._uninstall:
            if self._associate:
                ops.open_default_apps_settings()
            if self.chk_launch.isChecked() and self._exe is not None:
                subprocess.Popen([str(self._exe)], cwd=str(self._exe.parent), close_fds=True)
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._busy:
            event.ignore()
            return
        if self._removal_dir is not None and self.stack.currentIndex() == PAGE_DONE:
            ops.schedule_folder_removal(self._removal_dir)
        super().closeEvent(event)
        QApplication.quit()

    # -- painting ------------------------------------------------------------
    def _tick(self) -> None:
        self._phase += 0.012
        self.update(QRect(0, 0, LEFT_W, HEIGHT))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        outline = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(outline, RADIUS, RADIUS)
        p.setClipPath(clip)
        p.fillPath(clip, QColor(SURFACE))

        # ---- brand panel -----------------------------------------------------
        panel = QRectF(0, 0, LEFT_W, HEIGHT)
        base = QLinearGradient(panel.topLeft(), panel.bottomRight())
        base.setColorAt(0.0, QColor("#141838"))
        base.setColorAt(1.0, QColor("#0C0E1E"))
        p.fillRect(panel, base)

        a, b = math.sin(self._phase), math.cos(self._phase * 0.8)
        for centre, colour, radius in (
            (QPointF(70 + 26 * a, 96 + 18 * b), LOGO_A, 250),
            (QPointF(230 - 24 * b, 430 + 22 * a), LOGO_B, 270),
        ):
            glow = QRadialGradient(centre, radius)
            c0, c1 = QColor(colour), QColor(colour)
            c0.setAlpha(120)
            c1.setAlpha(0)
            glow.setColorAt(0.0, c0)
            glow.setColorAt(1.0, c1)
            p.fillRect(panel, glow)

        # lens rings, echoing the logo
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, ring in enumerate((150, 220, 300)):
            p.setPen(QPen(QColor(255, 255, 255, 16 - i * 4), 1.0))
            p.drawEllipse(QPointF(LEFT_W - 10, HEIGHT + 20), ring, ring)

        p.drawPixmap(QRectF(34, 52, 84, 84), self._logo, QRectF(self._logo.rect()))
        font = QFont(self.font())
        font.setPixelSize(34)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(34, 156, LEFT_W - 50, 44), Qt.AlignmentFlag.AlignVCenter, "Lumina")
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor(233, 236, 245, 175))
        p.drawText(
            QRectF(34, 204, LEFT_W - 60, 48),
            int(Qt.TextFlag.TextWordWrap),
            "A quiet place for your pictures.",
        )

        labels = ("Confirm", "Removing", "Done") if self._uninstall else ("Options", "Installing", "Finish")
        font.setPixelSize(12)
        p.setFont(font)
        for i, text in enumerate(labels):
            y = HEIGHT - 150 + i * 30
            active = i <= self._step
            centre = QPointF(44, y)
            if active:
                grad = QLinearGradient(centre.x() - 6, y - 6, centre.x() + 6, y + 6)
                grad.setColorAt(0.0, LOGO_A)
                grad.setColorAt(1.0, LOGO_B)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(grad)
                p.drawEllipse(centre, 5.5 if i == self._step else 4.0, 5.5 if i == self._step else 4.0)
            else:
                p.setPen(QPen(QColor(255, 255, 255, 60), 1.3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(centre, 4.0, 4.0)
            p.setPen(QColor(255, 255, 255, 235 if i == self._step else (150 if active else 95)))
            p.drawText(QRectF(60, y - 10, 180, 20), Qt.AlignmentFlag.AlignVCenter, text)

        font.setPixelSize(11)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 80))
        p.drawText(QRectF(34, HEIGHT - 44, 200, 20), Qt.AlignmentFlag.AlignVCenter, f"Version {__version__}")

        p.setPen(QPen(QColor(255, 255, 255, 18), 1.0))
        p.drawLine(QPointF(LEFT_W, 0), QPointF(LEFT_W, HEIGHT))

        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(outline, RADIUS, RADIUS)
        p.end()


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def _make_app() -> QApplication:
    # PyQt aborts the process on an unhandled exception inside an event
    # handler; report it instead of vanishing.
    def hook(kind, value, tb) -> None:
        import traceback

        traceback.print_exception(kind, value, tb)

    sys.excepthook = hook
    native.set_app_user_model_id("Lumina.Setup.1")
    app = QApplication(sys.argv)
    app.setApplicationName("Lumina Setup")
    app.setStyle("Fusion")
    family = pick_ui_font()
    font = QFont(family)
    font.setPointSizeF(9.75)
    app.setFont(font)
    app.setStyleSheet(base_qss(family))
    app.setWindowIcon(make_app_icon())
    return app


def _centre(window: QWidget) -> None:
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        window.move(area.center().x() - window.width() // 2, area.center().y() - window.height() // 2)


def run_installer() -> int:
    app = _make_app()
    window = Wizard()
    _centre(window)
    window.show()
    native.apply_dark_window(window)
    return app.exec()


def installed_location() -> Path:
    """Where the running (or registered) copy of Lumina lives."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ops.UNINSTALL_KEY) as handle:
            return Path(winreg.QueryValueEx(handle, "InstallLocation")[0])
    except OSError:
        return Path(ops.default_dir())


def run_uninstaller(silent: bool = False) -> int:
    directory = installed_location()
    if silent:
        ops.uninstall(directory)
        ops.schedule_folder_removal(directory)
        return 0
    app = _make_app()
    window = Wizard(uninstall=True, install_dir=directory)
    _centre(window)
    window.show()
    native.apply_dark_window(window)
    return app.exec()
