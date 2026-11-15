"""Hand-drawn vector icons, icon buttons and pill buttons.

Everything is painted with QPainter so the app needs no image assets and
stays crisp on any display scale factor.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from .theme import (
    ACCENT,
    ACCENT_BRIGHT,
    ACCENT_DEEP,
    DANGER,
    INK,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
)


def mix(a: QColor | str, b: QColor | str, t: float) -> QColor:
    """Linear colour interpolation, alpha included."""
    ca, cb = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
        round(ca.alpha() + (cb.alpha() - ca.alpha()) * t),
    )


# --- icon painters (24 x 24 design grid) -----------------------------------


def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _close(p: QPainter) -> None:
    _line(p, 7.4, 7.4, 16.6, 16.6)
    _line(p, 16.6, 7.4, 7.4, 16.6)


def _minimise(p: QPainter) -> None:
    _line(p, 6.8, 15.2, 17.2, 15.2)


def _maximise(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(6.4, 6.4, 11.2, 11.2), 2.4, 2.4)


def _restore(p: QPainter) -> None:
    path = QPainterPath(QPointF(9.2, 5.6))
    path.lineTo(17.6, 5.6)
    path.lineTo(17.6, 13.6)
    p.drawPath(path)
    p.drawRoundedRect(QRectF(5.4, 8.8, 9.4, 9.4), 2.0, 2.0)


def _chevron_down(p: QPainter) -> None:
    path = QPainterPath(QPointF(7.2, 9.8))
    path.lineTo(12, 14.4)
    path.lineTo(16.8, 9.8)
    p.drawPath(path)


def _chevron_up(p: QPainter) -> None:
    path = QPainterPath(QPointF(7.2, 14.2))
    path.lineTo(12, 9.6)
    path.lineTo(16.8, 14.2)
    p.drawPath(path)


def _chevron_left(p: QPainter) -> None:
    path = QPainterPath(QPointF(14.6, 6.4))
    path.lineTo(9.2, 12)
    path.lineTo(14.6, 17.6)
    p.drawPath(path)


def _chevron_right(p: QPainter) -> None:
    path = QPainterPath(QPointF(9.4, 6.4))
    path.lineTo(14.8, 12)
    path.lineTo(9.4, 17.6)
    p.drawPath(path)


def _plus(p: QPainter) -> None:
    _line(p, 12, 7.2, 12, 16.8)
    _line(p, 7.2, 12, 16.8, 12)


def _minus(p: QPainter) -> None:
    _line(p, 7.2, 12, 16.8, 12)


def _fit(p: QPainter) -> None:
    path = QPainterPath(QPointF(4.4, 9.2))
    path.lineTo(4.4, 4.4)
    path.lineTo(9.2, 4.4)
    p.drawPath(path)

    path = QPainterPath(QPointF(14.8, 4.4))
    path.lineTo(19.6, 4.4)
    path.lineTo(19.6, 9.2)
    p.drawPath(path)

    path = QPainterPath(QPointF(19.6, 14.8))
    path.lineTo(19.6, 19.6)
    path.lineTo(14.8, 19.6)
    p.drawPath(path)

    path = QPainterPath(QPointF(9.2, 19.6))
    path.lineTo(4.4, 19.6)
    path.lineTo(4.4, 14.8)
    p.drawPath(path)


def _actual(p: QPainter) -> None:
    font = QFont("Segoe UI")
    font.setPixelSize(10)
    font.setWeight(QFont.Weight.DemiBold)
    p.setFont(font)
    p.setPen(QColor(p.pen().color()))
    p.drawText(QRectF(0, 0, 24, 24), Qt.AlignmentFlag.AlignCenter, "1:1")


def _rotate(p: QPainter) -> None:
    p.drawArc(QRectF(6.2, 6.2, 11.6, 11.6), 55 * 16, 265 * 16)
    path = QPainterPath(QPointF(14.1, 5.2))
    path.lineTo(17.9, 6.9)
    path.lineTo(14.6, 9.9)
    p.drawPath(path)


def _folder(p: QPainter) -> None:
    path = QPainterPath(QPointF(3.6, 7.4))
    path.quadTo(3.6, 6.0, 5.0, 6.0)
    path.lineTo(9.0, 6.0)
    path.lineTo(10.7, 8.0)
    path.lineTo(19.0, 8.0)
    path.quadTo(20.4, 8.0, 20.4, 9.4)
    path.lineTo(20.4, 16.6)
    path.quadTo(20.4, 18.0, 19.0, 18.0)
    path.lineTo(5.0, 18.0)
    path.quadTo(3.6, 18.0, 3.6, 16.6)
    path.closeSubpath()
    p.drawPath(path)


def _image(p: QPainter) -> None:
    colour = QColor(p.pen().color())
    width = p.pen().widthF()
    p.drawRoundedRect(QRectF(3.6, 4.6, 16.8, 14.8), 2.6, 2.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    p.drawEllipse(QPointF(8.6, 9.4), 1.5, 1.5)
    pen = QPen(colour)
    pen.setWidthF(width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(4.6, 17.4))
    path.lineTo(9.4, 12.2)
    path.lineTo(13.0, 16.2)
    path.lineTo(15.6, 13.4)
    path.lineTo(19.6, 17.8)
    p.drawPath(path)


def _dots(p: QPainter) -> None:
    p.setBrush(QColor(p.pen().color()))
    p.setPen(Qt.PenStyle.NoPen)
    for x in (5.8, 12.0, 18.2):
        p.drawEllipse(QPointF(x, 12.0), 1.65, 1.65)


def _check(p: QPainter) -> None:
    path = QPainterPath(QPointF(5.2, 12.6))
    path.lineTo(9.8, 17.2)
    path.lineTo(18.8, 7.0)
    p.drawPath(path)


def _info(p: QPainter) -> None:
    p.drawEllipse(QPointF(12, 12), 8.4, 8.4)
    _line(p, 12, 11.0, 12, 16.6)
    p.setBrush(QColor(p.pen().color()))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(12, 7.9), 1.05, 1.05)


def _copy(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(8.4, 8.4, 10.4, 10.4), 2.4, 2.4)
    path = QPainterPath(QPointF(15.6, 5.2))
    path.lineTo(5.2, 5.2)
    path.lineTo(5.2, 15.6)
    p.drawPath(path)


_ICONS: dict[str, Callable[[QPainter], None]] = {
    "close": _close,
    "min": _minimise,
    "max": _maximise,
    "restore": _restore,
    "chevron-down": _chevron_down,
    "chevron-up": _chevron_up,
    "chevron-left": _chevron_left,
    "chevron-right": _chevron_right,
    "plus": _plus,
    "minus": _minus,
    "fit": _fit,
    "actual": _actual,
    "rotate": _rotate,
    "folder": _folder,
    "image": _image,
    "dots": _dots,
    "check": _check,
    "info": _info,
    "copy": _copy,
}


def draw_icon(
    painter: QPainter,
    name: str,
    box: QRectF,
    color: QColor | str,
    weight: float = 1.65,
) -> None:
    if name not in _ICONS:
        return
    scale = min(box.width(), box.height()) / 24.0
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(box.center() - QPointF(12 * scale, 12 * scale))
    painter.scale(scale, scale)
    pen = QPen(QColor(color))
    pen.setWidthF(weight)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _ICONS[name](painter)
    painter.restore()


def make_app_icon(size: int = 256) -> QIcon:
    """Programmatic brand mark so the app ships without asset files."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    pad = size * 0.055
    rect = QRectF(pad, pad, size - pad * 2, size - pad * 2)
    radius = size * 0.235
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#8FAAFF"))
    grad.setColorAt(1.0, QColor("#9B84FF"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, radius, radius)

    centre = rect.center()
    lens = size * 0.215
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(QColor(10, 12, 18, 225))
    pen.setWidthF(size * 0.055)
    p.setPen(pen)
    p.drawEllipse(centre, lens, lens)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(10, 12, 18, 240))
    p.drawEllipse(centre, size * 0.068, size * 0.068)

    pen = QPen(QColor(255, 255, 255, 110))
    pen.setWidthF(size * 0.038)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawArc(
        QRectF(centre.x() - lens, centre.y() - lens, lens * 2, lens * 2),
        50 * 16,
        62 * 16,
    )
    p.end()
    return QIcon(QPixmap.fromImage(image))


class LogoMark(QWidget):
    """The gradient lens mark used in the titlebar and the about box."""

    def __init__(self, size: int = 26, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = self._size
        rect = QRectF(0.5, 0.5, s - 1, s - 1)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor("#93ACFF"))
        grad.setColorAt(1.0, QColor("#A489FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, s * 0.3, s * 0.3)

        centre = rect.center()
        lens = s * 0.215
        pen = QPen(QColor(10, 12, 18, 215))
        pen.setWidthF(s * 0.07)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centre, lens, lens)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(10, 12, 18, 235))
        p.drawEllipse(centre, s * 0.075, s * 0.075)

        pen = QPen(QColor(255, 255, 255, 120))
        pen.setWidthF(s * 0.055)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(
            QRectF(centre.x() - lens, centre.y() - lens, lens * 2, lens * 2),
            50 * 16,
            60 * 16,
        )
        p.end()


def _hover_anim(widget: QWidget, start: float, end: float, duration: int = 150):
    anim = QPropertyAnimation(widget, b"hoverT", widget)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    return anim


class IconButton(QAbstractButton):
    """Square, frameless button with a painted vector glyph."""

    def __init__(
        self,
        icon: str,
        *,
        size: int = 32,
        icon_size: int = 16,
        color: str = TEXT_DIM,
        hover_color: str = TEXT,
        hover_bg: QColor | None = None,
        checked_color: str = ACCENT,
        radius: int = 9,
        tooltip: str | None = None,
        checkable: bool = False,
        danger: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon = icon
        self._icon_px = icon_size
        self._color = QColor(color)
        self._hover_color = QColor(DANGER if danger else hover_color)
        self._hover_bg = hover_bg or QColor(255, 255, 255, 20)
        self._checked_color = QColor(checked_color)
        self._radius = radius
        self._danger = danger
        self._hover = 0.0
        self._anim: QPropertyAnimation | None = None

        self.setFixedSize(size, size)
        self.setCheckable(checkable)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if tooltip:
            self.setToolTip(tooltip)

    # -- animated hover -----------------------------------------------------
    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    hoverT = pyqtProperty(float, _get_hover, _set_hover)

    def _animate(self, target: float) -> None:
        if self._anim is not None:
            self._anim.stop()
        self._anim = _hover_anim(self, self._hover, target)
        self._anim.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate(0.0)
        super().leaveEvent(event)

    def set_icon(self, name: str) -> None:
        if name != self._icon:
            self._icon = name
            self.update()

    # -- painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        active = max(self._hover, 1.0 if self.isChecked() else 0.0)

        if active > 0.01 and self.isEnabled():
            if self._danger and self._hover > 0.01:
                bg = QColor(255, 96, 96, int(46 * self._hover))
            else:
                bg = QColor(self._hover_bg)
                bg.setAlpha(int(bg.alpha() * min(1.0, active)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, self._radius, self._radius)

        base = self._checked_color if self.isChecked() else self._color
        colour = mix(base, self._hover_color, self._hover)
        if not self.isEnabled():
            colour.setAlpha(80)

        inset = (min(rect.width(), rect.height()) - self._icon_px) / 2
        draw_icon(p, self._icon, rect.adjusted(inset, inset, -inset, -inset), colour)
        p.end()


class PillButton(QAbstractButton):
    """Text button with optional leading glyph and trailing chevron."""

    def __init__(
        self,
        text: str,
        *,
        icon: str | None = None,
        chevron: bool = False,
        variant: str = "ghost",
        height: int = 30,
        radius: int = 9,
        pad: int | None = None,
        font_px: int = 12,
        tooltip: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._icon = icon
        self._chevron = chevron
        self._variant = variant
        self._radius = radius
        self._pad = pad if pad is not None else (15 if variant == "accent" else 11)
        self._hover = 0.0
        self._anim: QPropertyAnimation | None = None

        font = self.font()
        font.setPixelSize(font_px)
        font.setWeight(
            QFont.Weight.DemiBold if variant == "accent" else QFont.Weight.Medium
        )
        self.setFont(font)

        self.setFixedHeight(height)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if tooltip:
            self.setToolTip(tooltip)

    # -- text ---------------------------------------------------------------
    def text(self) -> str:  # noqa: N802
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        width = fm.horizontalAdvance(self._text) + self._pad * 2
        if self._icon:
            width += 16 + 7
        if self._chevron:
            width += 9 + 7
        return QSize(width, self.height())

    # -- hover --------------------------------------------------------------
    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    hoverT = pyqtProperty(float, _get_hover, _set_hover)

    def _animate(self, target: float) -> None:
        if self._anim is not None:
            self._anim.stop()
        self._anim = _hover_anim(self, self._hover, target)
        self._anim.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate(0.0)
        super().leaveEvent(event)

    # -- painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        h = self._hover
        accent = self._variant == "accent"

        if accent:
            top = mix("#8DA8FF", ACCENT_BRIGHT, h)
            bottom = mix(ACCENT_DEEP, ACCENT, h)
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, top)
            grad.setColorAt(1.0, bottom)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(rect, self._radius, self._radius)
            label_colour = QColor(INK)
        else:
            if h > 0.01:
                bg = QColor(255, 255, 255, int(18 * h))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(rect, self._radius, self._radius)
            border = QColor(255, 255, 255, int(20 + 34 * h))
            pen = QPen(border)
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, self._radius, self._radius)
            label_colour = mix(TEXT_DIM, "#FFFFFF", h)

        fm = self.fontMetrics()
        x = float(self._pad)
        mid = rect.center().y() + 0.5

        if self._icon:
            draw_icon(
                p,
                self._icon,
                QRectF(x, mid - 8, 16, 16),
                QColor(INK) if accent else label_colour,
                1.7,
            )
            x += 16 + 7

        p.setPen(label_colour)
        p.setFont(self.font())
        baseline = mid + (fm.ascent() - fm.descent()) / 2.0
        p.drawText(QPointF(x, baseline), self._text)
        x += fm.horizontalAdvance(self._text)

        if self._chevron:
            chev = QColor(INK) if accent else mix(TEXT_FAINT, label_colour, h)
            draw_icon(p, "chevron-down", QRectF(x + 7, mid - 4.5, 9, 9), chev, 1.9)

        p.end()
