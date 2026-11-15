"""The main window: frameless shell, custom titlebar and gallery wiring."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QByteArray, QPoint, QRect, QRectF, QSettings, Qt, QTimer
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import native
from .gallery import CARD_SIZES, GalleryView
from .icons import IconButton, LogoMark, PillButton, make_app_icon
from .lightbox import Lightbox
from .theme import SURFACE, TEXT_DIM, TEXT_FAINT
from .thumbs import IMAGE_FILTER, IMAGE_SUFFIXES, ThumbnailService
from .ui import AboutDialog, Divider, DropOverlay, ElideLabel, add_action, make_menu

SHADOW = 16
EDGE_LEFT, EDGE_RIGHT, EDGE_TOP, EDGE_BOTTOM = 1, 2, 4, 8
SORT_OPTIONS = (
    ("Name (A–Z)", "name"),
    ("Date modified (newest)", "date"),
    ("Size (largest)", "size"),
    ("File type", "type"),
)


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def _size(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


class TitleBar(QFrame):
    """Draggable custom titlebar with dropdown menus and window buttons."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.setObjectName("titlebar")
        self.setFixedHeight(52)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 9, 0)
        layout.setSpacing(8)

        layout.addWidget(LogoMark(24))

        self.wordmark = QLabel("Lumina")
        self.wordmark.setObjectName("wordmark")
        layout.addWidget(self.wordmark)
        layout.addSpacing(2)
        layout.addWidget(Divider())

        self.context = ElideLabel("No folder open", Qt.TextElideMode.ElideMiddle)
        self.context.setObjectName("context")
        self.context.setFixedWidth(158)
        self.context.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.context, 0)
        layout.addSpacing(6)

        self.file_btn = PillButton("File", chevron=True, height=28, pad=10, font_px=12)
        self.view_btn = PillButton("View", chevron=True, height=28, pad=10, font_px=12)
        self.file_btn.clicked.connect(lambda: window.show_file_menu(self.file_btn))
        self.view_btn.clicked.connect(lambda: window.show_view_menu(self.view_btn))
        layout.addWidget(self.file_btn)
        layout.addWidget(self.view_btn)
        layout.addStretch(1)

        self.min_btn = IconButton("min", size=34, radius=8, tooltip="Minimise")
        self.max_btn = IconButton("max", size=34, radius=8, tooltip="Maximise")
        self.close_btn = IconButton("close", size=34, radius=8, danger=True, tooltip="Close")
        self.min_btn.clicked.connect(window.showMinimized)
        self.max_btn.clicked.connect(window.toggle_maximised)
        self.close_btn.clicked.connect(window.close)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def set_context(self, text: str, tooltip: str = "") -> None:
        self.context.set_full_text(text)
        self.context.setToolTip(tooltip or text)

    def set_maximised(self, maximised: bool) -> None:
        self.max_btn.set_icon("restore" if maximised else "max")
        self.max_btn.setToolTip("Restore" if maximised else "Maximise")

    # -- window dragging ----------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().start_drag()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().toggle_maximised()
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(880, 600)
        self.setWindowTitle("Lumina")
        self.setWindowIcon(make_app_icon())

        self._settings = QSettings("Lumina", "LuminaViewer")
        self._thumbs = ThumbnailService(self)
        self._paths: list[str] = []
        self._folder: str | None = None
        self._sort = str(self._settings.value("sort", "name"))
        size_key = str(self._settings.value("cardSize", "comfortable"))
        self._card_size_key = size_key if size_key in CARD_SIZES else "comfortable"
        self._maxed = False
        self._edge = 0
        self._viewer_open = False
        self._was_maximised = False
        self._was_fullscreen = False
        self._saved_geometry: QRect | None = None
        self._pre_fullscreen_max = False
        self._shadow_cache: tuple[tuple, QPixmap] | None = None

        self._build_ui()
        self._build_actions()
        self._restore_geometry()
        self._sync_frame()

        native.apply_dark_window(self)
        native.set_border_colour(self, "#0f1117")

    # -- construction -------------------------------------------------------
    def _build_ui(self) -> None:
        self._shell = QWidget(self)
        self.setCentralWidget(self._shell)
        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        shell_layout.setSpacing(0)

        self.root = QFrame()
        self.root.setObjectName("root")
        shell_layout.addWidget(self.root)

        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.titlebar = TitleBar(self)
        root_layout.addWidget(self.titlebar)

        self.gallery = GalleryView(self._thumbs)
        self.gallery.set_card_size(CARD_SIZES[self._card_size_key])
        self.gallery.activated.connect(self._open_for_path)
        self.gallery.open_folder_requested.connect(self.open_folder)
        self.gallery.open_image_requested.connect(self.open_image)
        root_layout.addWidget(self.gallery, 1)

        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(34)
        footer.setStyleSheet(
            f"QFrame#footer {{ border-top: 1px solid rgba(255,255,255,18);"
            f" background: transparent; }}"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 0, 16, 0)
        footer_layout.setSpacing(10)

        self.count_label = QLabel("No images")
        self.count_label.setObjectName("footer")
        footer_layout.addWidget(self.count_label)
        footer_layout.addWidget(Divider())
        self.folder_label = ElideLabel("", Qt.TextElideMode.ElideMiddle)
        self.folder_label.setObjectName("footer")
        self.folder_label.setMinimumWidth(80)
        footer_layout.addWidget(self.folder_label, 1)

        hint = QLabel("Drag & drop images  ·  Ctrl+O to open")
        hint.setObjectName("footer")
        footer_layout.addWidget(hint)
        root_layout.addWidget(footer)

        self.drop = DropOverlay(self)
        self.drop.setGeometry(self.root.geometry())

        self.viewer = Lightbox(self._thumbs, self)
        self.viewer.closed.connect(self._on_viewer_closed)
        self.viewer.hide()

        self._update_status()

    def _build_actions(self) -> None:
        self.act_open_image = QAction("Open image…", self)
        self.act_open_image.setShortcut(QKeySequence("Ctrl+O"))
        self.act_open_image.triggered.connect(self.open_image)
        self.addAction(self.act_open_image)

        self.act_open_folder = QAction("Open folder…", self)
        self.act_open_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_open_folder.triggered.connect(self.open_folder)
        self.addAction(self.act_open_folder)

        self.act_fullscreen = QAction("Full screen", self)
        self.act_fullscreen.setShortcut(QKeySequence("F11"))
        self.act_fullscreen.triggered.connect(self.toggle_fullscreen)
        self.addAction(self.act_fullscreen)

        self.act_reload = QAction("Reload folder", self)
        self.act_reload.setShortcut(QKeySequence("F5"))
        self.act_reload.triggered.connect(self._reload_folder)
        self.addAction(self.act_reload)

        self.act_quit = QAction("Exit", self)
        self.act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self.act_quit.triggered.connect(self.close)
        self.addAction(self.act_quit)

    def _restore_geometry(self) -> None:
        saved = self._settings.value("geometry")
        if isinstance(saved, QByteArray) and not saved.isEmpty():
            self.restoreGeometry(saved)
        else:
            self.resize(1180, 780)
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(
                    area.center().x() - self.width() // 2,
                    area.center().y() - self.height() // 2,
                )

    # -- frame / chrome -----------------------------------------------------
    def _sync_frame(self) -> None:
        maxed = self.isMaximized() or self.isFullScreen() or self._viewer_open
        if maxed != self._maxed:
            self._maxed = maxed
            self.root.setProperty("maximised", maxed)
            self.root.style().unpolish(self.root)
            self.root.style().polish(self.root)
            margin = 0 if maxed else SHADOW
            self._shell.layout().setContentsMargins(margin, margin, margin, margin)
            self.update()
        self.titlebar.set_maximised(self.isMaximized())
        self.drop.setGeometry(self.root.geometry())

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self._sync_frame()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.viewer.setGeometry(self.rect())
        self.drop.setGeometry(self.root.geometry())

    def _shadow_pixmap(self) -> QPixmap:
        """The soft drop shadow, rendered once per size instead of per repaint.

        The window is translucent, so *every* repaint of any child (a hover
        fade, a thumbnail arriving) also repaints this widget underneath it;
        drawing 16 anti-aliased rounded rects each time was pure waste.
        """
        root_rect = QRect(self.root.mapTo(self, QPoint(0, 0)), self.root.size())
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), root_rect.getRect(), dpr)
        if self._shadow_cache is not None and self._shadow_cache[0] == key:
            return self._shadow_cache[1]

        pm = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        rect = root_rect.toRectF()
        for i in range(SHADOW, 0, -1):
            t = 1.0 - i / (SHADOW + 1)
            alpha = int(9 * t * t)
            if alpha <= 0:
                continue
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(rect.adjusted(-i, -i + 5, i, i + 5), 14 + i, 14 + i)
        p.end()
        self._shadow_cache = (key, pm)
        return pm

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._maxed or self._viewer_open:
            return
        dpr = self.devicePixelRatioF()
        dirty = event.rect()
        p = QPainter(self)
        p.drawPixmap(
            QRectF(dirty),
            self._shadow_pixmap(),
            QRectF(dirty.x() * dpr, dirty.y() * dpr, dirty.width() * dpr, dirty.height() * dpr),
        )
        p.end()

    # -- window behaviour ---------------------------------------------------
    def start_drag(self) -> None:
        handle = self.windowHandle()
        if handle is None:
            return
        if self.isMaximized():
            ratio = (QCursor.pos().x() - self.geometry().x()) / max(1, self.width())
            self.showNormal()
            self._sync_frame()
            width = self.width()
            self.move(
                int(QCursor.pos().x() - width * ratio),
                max(0, QCursor.pos().y() - 26),
            )
        handle.startSystemMove()

    def toggle_maximised(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_frame()

    def toggle_fullscreen(self) -> None:
        if self._viewer_open:
            return
        if self.isFullScreen():
            if self._pre_fullscreen_max:
                self.showMaximized()
            else:
                self.showNormal()
        else:
            self._pre_fullscreen_max = self.isMaximized()
            self.showFullScreen()
        self._sync_frame()

    def _edge_at(self, pos: QPoint) -> int:
        zone = 11
        if self._maxed or self._viewer_open:
            return 0
        edges = 0
        if pos.x() <= zone:
            edges |= EDGE_LEFT
        if pos.x() >= self.width() - zone:
            edges |= EDGE_RIGHT
        if pos.y() <= zone:
            edges |= EDGE_TOP
        if pos.y() >= self.height() - zone:
            edges |= EDGE_BOTTOM
        return edges

    @staticmethod
    def _qt_edge(bits: int) -> Qt.Edge:
        edge = Qt.Edge(0)
        if bits & EDGE_LEFT:
            edge |= Qt.Edge.LeftEdge
        if bits & EDGE_RIGHT:
            edge |= Qt.Edge.RightEdge
        if bits & EDGE_TOP:
            edge |= Qt.Edge.TopEdge
        if bits & EDGE_BOTTOM:
            edge |= Qt.Edge.BottomEdge
        return edge

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        edge = self._edge_at(event.position().toPoint())
        self._edge = edge
        if not edge:
            self.unsetCursor()
        else:
            horizontal = bool(edge & (EDGE_LEFT | EDGE_RIGHT))
            vertical = bool(edge & (EDGE_TOP | EDGE_BOTTOM))
            if horizontal and vertical:
                diagonal = EDGE_LEFT | EDGE_TOP
                if edge in (diagonal, EDGE_RIGHT | EDGE_BOTTOM):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif horizontal:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif vertical:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._edge:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemResize(self._qt_edge(self._edge))
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._edge = 0
        self.unsetCursor()
        super().leaveEvent(event)

    # -- menus --------------------------------------------------------------
    def show_file_menu(self, button: QWidget) -> None:
        menu = make_menu(self)
        menu.addAction(self.act_open_image)
        menu.addAction(self.act_open_folder)
        menu.addSeparator()

        recent_menu = make_menu(menu)
        recent_menu.setTitle("Recent folders")
        recent = self._recent()
        if recent:
            for folder in recent[:8]:
                action = QAction(os.path.basename(folder.rstrip("\\/")) or folder, recent_menu)
                action.setToolTip(folder)
                action.triggered.connect(
                    lambda _=False, f=folder: self.load_folder(f)
                )
                recent_menu.addAction(action)
            recent_menu.addSeparator()
            add_action(recent_menu, "Clear list", self._clear_recent)
        else:
            add_action(recent_menu, "No recent folders", None, enabled=False)
        menu.addMenu(recent_menu)

        if self._folder:
            menu.addAction(self.act_reload)
        menu.addSeparator()
        add_action(menu, "About Lumina", self.show_about)
        menu.addAction(self.act_quit)

        menu.exec(button.mapToGlobal(QPoint(0, button.height() + 7)))

    def show_view_menu(self, button: QWidget) -> None:
        menu = make_menu(self)
        sizes = make_menu(menu)
        sizes.setTitle("Thumbnail size")
        for label, key in (
            ("Compact", "compact"),
            ("Comfortable", "comfortable"),
            ("Large", "large"),
        ):
            mark = "✓  " if key == self._card_size_key else "     "
            add_action(
                sizes,
                f"{mark}{label}",
                lambda _=False, k=key: self.set_card_size(k),
            )
        menu.addMenu(sizes)

        sorts = make_menu(menu)
        sorts.setTitle("Sort by")
        for label, key in SORT_OPTIONS:
            mark = "✓  " if key == self._sort else "     "
            add_action(
                sorts,
                f"{mark}{label}",
                lambda _=False, k=key: self.set_sort(k),
            )
        menu.addMenu(sorts)
        menu.addSeparator()
        menu.addAction(self.act_fullscreen)
        menu.exec(button.mapToGlobal(QPoint(0, button.height() + 7)))

    def show_about(self) -> None:
        dialog = AboutDialog(self)
        native.apply_dark_window(dialog)
        dialog.exec()

    def _clear_recent(self) -> None:
        self._settings.setValue("recent", [])
        self._settings.sync()

    def _recent(self) -> list[str]:
        value = self._settings.value("recent", [])
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        try:
            return [str(item) for item in value]
        except TypeError:
            return []

    # -- collections --------------------------------------------------------
    def open_folder(self) -> None:
        start = self._folder or str(Path.home() / "Pictures")
        folder = QFileDialog.getExistingDirectory(
            self, "Open a folder of images", start
        )
        if folder:
            self.load_folder(folder)

    def _reload_folder(self) -> None:
        if self._folder:
            self.load_folder(self._folder)

    def load_folder(self, folder: str, *, select: str | None = None) -> None:
        paths = self._scan_folder(folder)
        self._folder = folder
        self._paths = self._sort_paths(paths)
        self._remember_folder(folder)
        self._refresh_collection()
        if select:
            try:
                index = self._paths.index(select)
            except ValueError:
                index = 0
            self._open_viewer(index)

    def _scan_folder(self, folder: str) -> list[str]:
        found: list[str] = []
        try:
            for entry in os.scandir(folder):
                if not entry.is_file():
                    continue
                if os.path.splitext(entry.name)[1].lower() in IMAGE_SUFFIXES:
                    found.append(entry.path)
        except OSError:
            return []
        return found

    def _sort_paths(self, paths: list[str]) -> list[str]:
        if self._sort == "date":
            return sorted(paths, key=_mtime, reverse=True)
        if self._sort == "size":
            return sorted(paths, key=_size, reverse=True)
        if self._sort == "type":
            return sorted(
                paths,
                key=lambda p: (
                    os.path.splitext(p)[1].lower(),
                    os.path.basename(p).lower(),
                ),
            )
        return sorted(paths, key=lambda p: os.path.basename(p).lower())

    def _refresh_collection(self) -> None:
        self.gallery.set_paths(self._paths)
        self._update_status()
        if self._folder:
            name = os.path.basename(self._folder.rstrip("\\/")) or self._folder
            self.titlebar.set_context(name, self._folder)
        else:
            self.titlebar.set_context("No folder open")

    def _update_status(self) -> None:
        count = len(self._paths)
        if count:
            self.count_label.setText(
                f"{count} image" + ("" if count == 1 else "s")
            )
        else:
            self.count_label.setText("No images")
        self.folder_label.set_full_text(self._folder or "")
        self.folder_label.setToolTip(self._folder or "")

    def _remember_folder(self, folder: str) -> None:
        recent = [f for f in self._recent() if f != folder]
        recent.insert(0, folder)
        self._settings.setValue("recent", recent[:8])
        self._settings.sync()

    def set_card_size(self, key: str) -> None:
        if key not in CARD_SIZES:
            return
        self._card_size_key = key
        self.gallery.set_card_size(CARD_SIZES[key])
        self._settings.setValue("cardSize", key)

    def set_sort(self, key: str) -> None:
        if key == self._sort:
            return
        self._sort = key
        self._settings.setValue("sort", key)
        if self._paths:
            self._paths = self._sort_paths(self._paths)
            self._refresh_collection()

    def open_path(self, path: str) -> None:
        """Open a specific file from the command line, with its folder around it."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            if os.path.isdir(path):
                self.load_folder(path)
            return
        folder = os.path.dirname(path)
        self._folder = folder
        self._paths = self._sort_paths(self._scan_folder(folder))
        if path not in self._paths:
            self._paths.append(path)
        self._remember_folder(folder)
        self._refresh_collection()
        self._open_viewer(self._paths.index(path))

    def open_image(self) -> None:
        start = self._folder or str(Path.home() / "Pictures")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open an image", start, IMAGE_FILTER
        )
        if not path:
            return
        folder = os.path.dirname(path)
        self._folder = folder
        self._paths = self._sort_paths(self._scan_folder(folder))
        if path not in self._paths:
            self._paths.append(path)
        self._remember_folder(folder)
        self._refresh_collection()
        self._open_viewer(self._paths.index(path))

    # -- viewer -------------------------------------------------------------
    def _open_for_path(self, path: str) -> None:
        try:
            index = self._paths.index(path)
        except ValueError:
            return
        self._open_viewer(index)

    def _open_viewer(self, index: int) -> None:
        if not self._paths:
            return
        index = max(0, min(len(self._paths) - 1, index))
        if self._viewer_open:
            self.viewer.open_at(self._paths, index)
            return
        self._was_fullscreen = self.isFullScreen()
        self._was_maximised = self.isMaximized()
        self._saved_geometry = self.geometry()
        self._viewer_open = True
        self.root.hide()
        self.drop.hide()
        self._sync_frame()
        self.showFullScreen()
        self.viewer.setGeometry(self.rect())
        self.viewer.open_at(self._paths, index)
        self.viewer.raise_()
        name = os.path.basename(self._paths[index])
        self.setWindowTitle(f"{name} — Lumina")

    def _on_viewer_closed(self) -> None:
        self._viewer_open = False
        self.root.show()
        if self._was_fullscreen:
            self.showFullScreen()
        elif self._was_maximised:
            self.showMaximized()
        else:
            self.showNormal()
            if self._saved_geometry is not None:
                self.setGeometry(self._saved_geometry)
        self.setWindowTitle("Lumina")
        self._sync_frame()
        self.gallery.setFocus()

    # -- drag & drop --------------------------------------------------------
    def _drop_targets(self, mime) -> list[str]:
        if not mime.hasUrls():
            return []
        result = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isdir(path):
                result.append(path)
            elif os.path.splitext(path)[1].lower() in IMAGE_SUFFIXES:
                result.append(path)
        return result

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._viewer_open:
            return
        if self._drop_targets(event.mimeData()):
            event.acceptProposedAction()
            self.drop.setGeometry(self.root.geometry())
            self.drop.show()
            self.drop.raise_()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._drop_targets(event.mimeData()):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.drop.hide()
        targets = self._drop_targets(event.mimeData())
        if not targets:
            return
        event.acceptProposedAction()
        folders = [t for t in targets if os.path.isdir(t)]
        if folders:
            self.load_folder(folders[0])
            return
        images = self._sort_paths(targets)
        self._folder = os.path.dirname(images[0])
        self._paths = images
        self._refresh_collection()
        self._open_viewer(0)

    # -- shortcuts / lifecycle ---------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.isFullScreen():
            self.showNormal()
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("sort", self._sort)
        self._settings.setValue("cardSize", self._card_size_key)
        self._settings.sync()
        self._thumbs.shutdown()
        super().closeEvent(event)
