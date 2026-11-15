"""Background thumbnail decoding with a small LRU cache.

Requests are served newest-first (so whatever is on screen *now* wins over what
was on screen a second ago) and a request that is no longer wanted by the time
a worker thread picks it up is dropped without decoding.
"""

from __future__ import annotations

import os
from collections import OrderedDict

from PyQt6.QtCore import QObject, QRunnable, QSize, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QImageReader, QPixmap

from .formats import IMAGE_FILTER, IMAGE_SUFFIXES, decode_pillow  # noqa: F401

_PREMULTIPLIED = QImage.Format.Format_ARGB32_Premultiplied


def decode_scaled(path: str, px: int) -> QImage:
    """Decode *path* no larger than needed to cover a ``px`` x ``px`` square."""
    image = QImage()
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        source = reader.size()
        if source.isValid() and source.width() > 0 and source.height() > 0:
            target = source.scaled(
                QSize(px, px), Qt.AspectRatioMode.KeepAspectRatioByExpanding
            )
            # Never ask the decoder for more pixels than the file holds.
            if target.width() > source.width() or target.height() > source.height():
                target = source
            reader.setScaledSize(target)
        image = reader.read()
    except Exception:
        image = QImage()

    if image.isNull():
        try:
            image = QImage(path)
        except Exception:
            image = QImage()

    if image.isNull():
        # Formats Qt has no plugin for (AVIF, HEIC, JPEG XL, JPEG 2000, ...).
        image = decode_pillow(path, px)

    # Convert on the worker thread so QPixmap.fromImage() on the UI thread is a
    # cheap, shallow wrap instead of a per-pixel format conversion.
    if not image.isNull() and image.format() != _PREMULTIPLIED:
        image = image.convertToFormat(_PREMULTIPLIED)
    return image


class _JobSignals(QObject):
    done = pyqtSignal(object, object)  # key, QImage (null = failed, None = skipped)


class _ThumbJob(QRunnable):
    def __init__(self, service: "ThumbnailService", key: tuple[str, int]) -> None:
        super().__init__()
        self._service = service
        self._signals = service._signals
        self._key = key
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D401
        image: QImage | None
        try:
            if self._key not in self._service._wanted:
                # Scrolled away / folder changed while this was still queued.
                image = None
            else:
                image = decode_scaled(*self._key)
        except Exception:
            image = QImage()

        try:
            self._signals.done.emit(self._key, image)
        except RuntimeError:
            # The service was destroyed while this job was still running.
            pass


class ThumbnailService(QObject):
    """Decodes thumbnails off the UI thread and hands back QPixmaps."""

    ready = pyqtSignal(str, int, QPixmap)

    def __init__(self, parent: QObject | None = None, cache_limit: int = 320) -> None:
        super().__init__(parent)
        self._cache: "OrderedDict[tuple[str, int], QPixmap]" = OrderedDict()
        self._best: dict[str, int] = {}
        self._pending: set[tuple[str, int]] = set()
        self._failed: set[tuple[str, int]] = set()
        self._cache_limit = cache_limit

        # Keys the worker threads are allowed to decode.  Replaced wholesale
        # (never mutated) so reading it from a worker thread is race-free.
        self._pinned: set[tuple[str, int]] = set()
        self._owners: dict[str, frozenset[tuple[str, int]]] = {}
        self._wanted: frozenset[tuple[str, int]] = frozenset()
        self._priority = 0

        self._signals = _JobSignals(self)
        self._signals.done.connect(self._deliver)

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(8, (os.cpu_count() or 4))))

    # -- public API ---------------------------------------------------------
    def cached(self, path: str, px: int) -> QPixmap | None:
        key = (path, px)
        pixmap = self._cache.get(key)
        if pixmap is not None:
            self._cache.move_to_end(key)
        return pixmap

    def any_cached(self, path: str) -> QPixmap | None:
        """Largest thumbnail we still hold for *path*, whatever its size."""
        px = self._best.get(path)
        if px is None:
            return None
        return self._cache.get((path, px))

    def request(self, path: str, px: int, owner: str | None = None) -> None:
        """Queue a decode.

        Requests made with an *owner* only run while that owner's latest
        :meth:`set_wanted` still lists the key (call it *before* requesting);
        requests with no owner always run.
        """
        if px <= 0:
            return
        key = (path, px)
        if key in self._cache or key in self._failed:
            return
        if key in self._pending:
            if owner is None and key not in self._pinned:
                self._pinned.add(key)
                self._rebuild_wanted()
            return
        if not os.path.isfile(path):
            self._failed.add(key)
            return
        self._pending.add(key)
        if owner is None:
            self._pinned.add(key)
            self._rebuild_wanted()
        self._priority = (self._priority + 1) % 1_000_000_000
        self._pool.start(_ThumbJob(self, key), self._priority)

    def set_wanted(self, owner: str, keys) -> None:
        """Declare exactly which keys *owner* still cares about."""
        self._owners[owner] = frozenset(keys)
        self._rebuild_wanted()

    def shutdown(self) -> None:
        self._wanted = frozenset()
        self._pool.clear()
        self._pool.waitForDone(1500)

    # -- internals ----------------------------------------------------------
    def _rebuild_wanted(self) -> None:
        wanted: set[tuple[str, int]] = set(self._pinned)
        for keys in self._owners.values():
            wanted |= keys
        self._wanted = frozenset(wanted)

    def _deliver(self, key: tuple[str, int], image: QImage | None) -> None:
        self._pending.discard(key)
        self._pinned.discard(key)
        if image is None:  # skipped: nobody wants it any more
            return
        if image.isNull():
            self._failed.add(key)
            return
        pixmap = QPixmap.fromImage(image)
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        if key[1] >= self._best.get(key[0], 0):
            self._best[key[0]] = key[1]
        while len(self._cache) > self._cache_limit:
            old_key, _ = self._cache.popitem(last=False)
            if self._best.get(old_key[0]) == old_key[1]:
                del self._best[old_key[0]]
        self.ready.emit(key[0], key[1], pixmap)
