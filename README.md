# Lumina

A fast, frameless image viewer for Windows, built with PyQt6.

Lumina opens on a dark thumbnail gallery. Clicking a photo drops you into a
full-screen viewer whose backdrop is a **50% black veil** — the desktop stays
visible behind the picture. The window chrome, icons and app logo are all
painted with `QPainter`, so there are no image assets to ship.

## Requirements

- Windows 10 or 11
- Python 3.9+
- `pip install -r requirements.txt` (PyQt6 6.5 or newer)

## Supported formats

| How | Formats |
| --- | --- |
| Qt (built in, fastest) | PNG, JPEG, **WebP** (lossy, lossless, alpha, animated), GIF (animated), BMP, TIFF, ICO, ICNS, TGA, SVG |
| Pillow (`Pillow>=11.3`) | **AVIF**, JPEG 2000 (`.jp2` `.j2k`), PSD, QOI, DDS, PCX, MPO |
| `pillow-heif` (optional) | **HEIC / HEIF** (iPhone photos) |
| `pillow-jxl-plugin` (optional) | **JPEG XL** |

Qt is always tried first; Pillow is only used for files Qt cannot read, so
common formats lose no speed. The optional packages are picked up
automatically when installed (and bundled by `build_exe.bat`); without them
Lumina just opens fewer formats. Camera RAW files (CR2, NEF, ARW, DNG) are not
supported.

## Running

```bat
run.bat
```

or, from a terminal:

```bat
python main.py                  :: open the gallery
python main.py photo.jpg        :: open one photo straight into the viewer
python main.py D:\Pictures      :: open a folder
```

Images can also be dropped onto the window, or a folder can be passed as the
first argument.

## Building Lumina.exe

The packaged build is a single, console-free executable with the app icon and
version data embedded:

```bat
pip install -r requirements-dev.txt
build_exe.bat
```

That writes `dist\Lumina.exe` (about 35 MB). It is self-contained — Python and
PyQt6 do not need to be installed on the machine that runs it. Double-click it,
or pass files and folders on the command line:

```bat
dist\Lumina.exe photo.jpg
```

The icon is generated from the same `QPainter` code by `tools/make_icon.py`
(`assets\lumina.ico`), so the .exe icon and the in-app icon always match.
Windows may show a SmartScreen prompt for an unsigned executable; choose
"More info" → "Run anyway".

## Installer

```bat
build_installer.bat
```

builds `dist\Lumina-Setup.exe` (about 75 MB): a branded, self-contained
installer with the app packed inside, so the target PC needs no Python or Qt.
It installs per user (no admin prompt) to `%LOCALAPPDATA%\Programs\Lumina` and
offers tick boxes for a **Start menu shortcut**, a **desktop shortcut** and
**Use Lumina for pictures** (registers Lumina for every image type, then opens
Windows' Default apps page, where you pick Lumina — Windows does not let
installers switch defaults silently).

Uninstall from *Settings → Apps*, or run `Lumina.exe --uninstall`. For
scripts: `Lumina-Setup.exe /S [--dir PATH] [--no-start-menu] [--no-desktop]
[--no-assoc]` installs silently and `Lumina.exe --uninstall --silent` removes
it. `build_exe.bat` alone now produces the one-folder app `dist\Lumina\`
(a 5 MB `Lumina.exe` plus its DLLs in `_internal`), which also starts faster
than the old single-file exe.

## Logs

Because the packaged app has no console, every uncaught exception, Qt warning
and start/exit event is appended to:

```
%LOCALAPPDATA%\Lumina\logs\lumina.log
```

The file rotates to `lumina.1.log` once it passes 512 KB. If Lumina ever exits
on its own, that log will say whether the window was closed, the event loop
quit, or an exception fired first.

A healthy session looks like:

```
--- Lumina started 2026-11-15 21:05:20 ---
last window closed
event loop quit
[C:\Users\...\lumina.log] exited with code 0
```

## Viewer controls

| Input | Action |
| --- | --- |
| `→` `↓` `Space` `Page Down` | Next image |
| `←` `↑` `Page Up` | Previous image |
| `Home` / `End` | First / last image |
| Mouse wheel | Zoom around the cursor |
| Drag | Pan (when zoomed in) |
| Double-click | Toggle fit / 100% |
| `+` / `-` | Zoom in / out |
| `0` | Fit to window |
| `1` | Actual size (100%) |
| `F11` | Toggle full screen |
| `Esc` | Close the viewer (or leave full screen) |

The top and bottom HUD bars slide away on their own after ~3 seconds of
inactivity and slide back when the mouse moves. They stay put while a menu is
open, while you are dragging the photo, or while the cursor is over a bar.

## Window and gallery

- Frameless window with a custom titlebar: drag to move, double-click to
  maximise, grab any edge to resize.
- `File` and `View` dropdown menus in the titlebar.
- Thumbnail sizes (compact / comfortable / large) and sort order (name, date,
  size, type) are remembered between sessions with `QSettings`.
- The gallery is virtualised: only the cards on screen are painted, and only
  those (plus a little look-ahead) get thumbnails decoded, newest request
  first, on a `QThreadPool` with an LRU pixmap cache. A folder of thousands of
  photos opens and scrolls as fast as a folder of dozens.
- The viewer decodes photos on worker threads, prefetches the next/previous
  ones, and shows the cached thumbnail while the full photo loads, so stepping
  through photos never blocks the UI.
- Recent folders, drag-and-drop overlay, context menu, and an About dialog.

## Layout

```
main.py           app entry point (also handles `--uninstall`)
setup_main.py     installer entry point (Lumina-Setup.exe)
lumina/
  window.py       MainWindow, TitleBar, menus, drag & drop, full-screen wiring
  gallery.py      virtualised thumbnail grid, hover cards, empty state
  lightbox.py     full-screen overlay: veil, HUD, filmstrip, keys
  canvas.py       zoom / pan / fit image canvas, async photo loading (and GIFs)
  thumbs.py       threaded, prioritised thumbnail decoding + cache
  formats.py      supported formats and the Pillow fallback decoder
  icons.py        vector icons, buttons, logo
  theme.py        palette, QSS, veil alpha
  ui.py           small widgets: menus, dividers, drop overlay, About
  native.py       DWM dark titlebar / border, taskbar identity
  log.py          crash / Qt message log for the windowed build
  setup/          installer: ops.py (files, shortcuts, registry), ui.py (window)
tools/
  make_icon.py    renders assets/lumina.ico from the same vector code
  make_payload.py zips the built app for the installer
build/
  version_info.txt, setup_version_info.txt   Windows file properties
assets/
  lumina.ico
dist/             build output (git-ignorable): Lumina-Setup.exe
```

## Notes

- The viewer is an in-window overlay rather than a second top-level window, so
  it never adds a second taskbar entry. While the viewer is open in full
  screen, the gallery root is hidden so the veil composites over the real
  desktop.
- The veil colour is `rgba(0, 0, 0, 128)` (`theme.VEIL_ALPHA`), which is exactly
  50% black. Lowering it reveals more of the desktop; raising it makes the
  photo stand out more.
