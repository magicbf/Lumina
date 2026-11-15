"""Colours, typography and global stylesheet for Lumina."""

from __future__ import annotations

from string import Template

from PyQt6.QtGui import QColor, QFontDatabase

# --- palette ---------------------------------------------------------------

INK = "#08090C"
SURFACE = "#0F1117"
SURFACE_ALT = "#14171F"
ELEVATED = "#181C26"

TEXT = "#E9ECF5"
TEXT_DIM = "#98A1B4"
TEXT_FAINT = "#69718A"

ACCENT = "#7C9CFF"
ACCENT_BRIGHT = "#A6BAFF"
ACCENT_DEEP = "#5F7DF0"
DANGER = "#FF6B6B"

STROKE = "rgba(255, 255, 255, 19)"        # ~7.5 %
STROKE_STRONG = "rgba(255, 255, 255, 38)"

# The viewer veil: exactly 50 % black, so the desktop stays visible behind it.
VEIL_ALPHA = 128

UI_FALLBACKS = (
    "Segoe UI Variable Text",
    "Segoe UI",
    "Inter",
    "SF Pro Text",
    "Noto Sans",
    "DejaVu Sans",
)


def pick_ui_font() -> str:
    """Return the nicest font family installed on this machine."""
    try:
        available = set(QFontDatabase.families())
    except Exception:  # pragma: no cover - defensive
        return "Segoe UI"
    for family in UI_FALLBACKS:
        if family in available:
            return family
    return "Sans Serif"


def tint(color: str | QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


# --- stylesheet ------------------------------------------------------------

_QSS = Template(
    """
QWidget {
    color: $TEXT;
    font-family: "$FAMILY";
    font-size: 13px;
}
QMainWindow {
    background: transparent;
}
QLabel {
    background: transparent;
}

/* ---- window shell --------------------------------------------------- */
QFrame#root {
    background-color: $SURFACE;
    border: 1px solid $STROKE;
    border-radius: 14px;
}
QFrame#root[viewer="true"] {
    background: transparent;
    border: none;
    border-radius: 0px;
}
QFrame#root[maximised="true"] {
    border-radius: 0px;
}
QFrame#vsep {
    background: $STROKE;
    border: none;
}
QFrame#hsep {
    background: $STROKE;
    border: none;
}

/* ---- typography ----------------------------------------------------- */
QLabel#wordmark {
    font-size: 13px;
    font-weight: 600;
    color: #F4F6FC;
}
QLabel#context {
    font-size: 12px;
    color: $TEXT_DIM;
}
QLabel#footer {
    font-size: 11px;
    color: $TEXT_FAINT;
}
QLabel#emptyTitle {
    font-size: 21px;
    font-weight: 600;
    color: #F2F4FA;
}
QLabel#emptyBody {
    font-size: 13px;
    color: $TEXT_DIM;
}
QLabel#emptyHint {
    font-size: 11px;
    color: $TEXT_FAINT;
}

/* ---- floating HUD --------------------------------------------------- */
QFrame#hud {
    background-color: rgba(15, 17, 23, 205);
    border: 1px solid $STROKE;
    border-radius: 15px;
}
QFrame#hud QLabel {
    background: transparent;
}
QLabel#hudTitle {
    font-size: 13px;
    font-weight: 600;
    color: #F4F6FC;
}
QLabel#hudMeta {
    font-size: 11px;
    color: $TEXT_DIM;
}
QWidget#filmInner {
    background: transparent;
}

/* ---- scrolling ------------------------------------------------------ */
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 6px 3px 6px 1px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 72);
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 1px 6px 3px 6px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-width: 40px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(255, 255, 255, 72);
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
    background: transparent;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* ---- menus ---------------------------------------------------------- */
QMenu {
    background-color: #151821;
    border: 1px solid $STROKE_STRONG;
    border-radius: 12px;
    padding: 6px;
}
QMenu::item {
    padding: 8px 34px 8px 14px;
    border-radius: 8px;
    color: #D8DDEA;
    font-size: 13px;
}
QMenu::item:selected {
    background-color: rgba(124, 156, 255, 42);
    color: #FFFFFF;
}
QMenu::item:disabled {
    color: rgba(216, 221, 234, 90);
}
QMenu::separator {
    height: 1px;
    background: $STROKE;
    margin: 6px 12px;
}
QMenu::right-arrow {
    width: 10px;
    height: 10px;
    margin-right: 12px;
}

/* ---- dialogs & tooltips --------------------------------------------- */
QDialog {
    background-color: $SURFACE_ALT;
}
QToolTip {
    background-color: #1B1F2A;
    color: $TEXT;
    border: 1px solid $STROKE_STRONG;
    border-radius: 7px;
    padding: 6px 9px;
    font-size: 12px;
}
"""
)


def base_qss(family: str | None = None) -> str:
    return _QSS.substitute(
        FAMILY=family or pick_ui_font(),
        TEXT=TEXT,
        TEXT_DIM=TEXT_DIM,
        TEXT_FAINT=TEXT_FAINT,
        SURFACE=SURFACE,
        SURFACE_ALT=SURFACE_ALT,
        STROKE=STROKE,
        STROKE_STRONG=STROKE_STRONG,
    )
