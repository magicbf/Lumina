"""Install / uninstall operations (no UI).  Everything is per-user (HKCU).

Kept free of PyQt-widget and Pillow imports so the installer stays small.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import winreg
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import __version__

APP_NAME = "Lumina"
EXE_NAME = "Lumina.exe"
PROG_ID = "Lumina.Image"
PUBLISHER = "Lumina"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Lumina"
CAPABILITIES_KEY = r"Software\Lumina\Capabilities"

# Every extension Lumina can open (superset: plugins decide at runtime).
ASSOC_EXTS = (
    ".jpg .jpeg .jpe .jfif .png .webp .gif .bmp .tif .tiff .ico .svg .tga "
    ".avif .heic .heif .hif .jxl .jp2 .j2k .jpx .qoi .psd .pcx .dds .mpo .icns"
).split()

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

Progress = Callable[[float, str], None]


class SetupError(Exception):
    """A problem worth showing to the user as-is."""


@dataclass
class InstallOptions:
    directory: str
    start_menu: bool = True
    desktop: bool = True
    associate: bool = True


# -- locations ---------------------------------------------------------------
def default_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return str(Path(base) / "Programs" / APP_NAME)


def _known_dir(kind: str) -> Path:
    from PyQt6.QtCore import QStandardPaths

    location = {
        "desktop": QStandardPaths.StandardLocation.DesktopLocation,
        "start": QStandardPaths.StandardLocation.ApplicationsLocation,
    }[kind]
    return Path(QStandardPaths.writableLocation(location))


def shortcut_paths() -> dict[str, Path]:
    return {
        "start_menu": _known_dir("start") / f"{APP_NAME}.lnk",
        "desktop": _known_dir("desktop") / f"{APP_NAME}.lnk",
    }


def payload_path() -> Path:
    """The zipped app folder bundled inside Setup.exe."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2] / "dist"))
    return root / "payload.zip"


def payload_size(path: Path | None = None) -> int:
    """Uncompressed size of the payload in bytes (0 if missing)."""
    path = path or payload_path()
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(info.file_size for info in archive.infolist())
    except (OSError, zipfile.BadZipFile):
        return 0


# -- install -----------------------------------------------------------------
def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _make_shortcut(lnk: Path, target: Path, workdir: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
        f"{_ps_quote(str(lnk))});"
        f"$s.TargetPath={_ps_quote(str(target))};"
        f"$s.WorkingDirectory={_ps_quote(str(workdir))};"
        f"$s.IconLocation={_ps_quote(str(target) + ',0')};"
        "$s.Description='Lumina image viewer';$s.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0 or not lnk.exists():
        raise SetupError(f"Could not create the shortcut {lnk.name}.")


def _set(
    root: int, key: str, name: str | None, value: str | bytes, kind: int = winreg.REG_SZ
) -> None:
    with winreg.CreateKeyEx(root, key, 0, winreg.KEY_SET_VALUE) as handle:
        winreg.SetValueEx(handle, name, 0, kind, value)


def _notify_shell() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass


def register_file_types(exe: Path) -> None:
    """Make Lumina a choosable app for every image type (HKCU, no admin)."""
    classes = r"Software\Classes"
    command = f'"{exe}" "%1"'
    _set(winreg.HKEY_CURRENT_USER, rf"{classes}\{PROG_ID}", None, "Lumina image")
    _set(winreg.HKEY_CURRENT_USER, rf"{classes}\{PROG_ID}\DefaultIcon", None, f"{exe},0")
    _set(winreg.HKEY_CURRENT_USER, rf"{classes}\{PROG_ID}\shell\open\command", None, command)

    app_key = rf"{classes}\Applications\{EXE_NAME}"
    _set(winreg.HKEY_CURRENT_USER, rf"{app_key}\shell\open\command", None, command)
    _set(winreg.HKEY_CURRENT_USER, f"{app_key}", "FriendlyAppName", APP_NAME)

    _set(winreg.HKEY_CURRENT_USER, CAPABILITIES_KEY, "ApplicationName", APP_NAME)
    _set(
        winreg.HKEY_CURRENT_USER,
        CAPABILITIES_KEY,
        "ApplicationDescription",
        "A fast, frameless image viewer",
    )
    for ext in ASSOC_EXTS:
        _set(
            winreg.HKEY_CURRENT_USER,
            rf"{classes}\{ext}\OpenWithProgids",
            PROG_ID,
            b"",
            winreg.REG_NONE,
        )
        _set(winreg.HKEY_CURRENT_USER, rf"{CAPABILITIES_KEY}\FileAssociations", ext, PROG_ID)
        _set(winreg.HKEY_CURRENT_USER, rf"{app_key}\SupportedTypes", ext, "")
    _set(
        winreg.HKEY_CURRENT_USER,
        r"Software\RegisteredApplications",
        APP_NAME,
        CAPABILITIES_KEY,
    )
    _notify_shell()


def _register_uninstall(directory: Path, exe: Path, size_kb: int) -> None:
    values = {
        "DisplayName": APP_NAME,
        "DisplayVersion": __version__,
        "Publisher": PUBLISHER,
        "DisplayIcon": str(exe),
        "InstallLocation": str(directory),
        "UninstallString": f'"{exe}" --uninstall',
        "QuietUninstallString": f'"{exe}" --uninstall --silent',
    }
    for name, value in values.items():
        _set(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, name, value)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as h:
        winreg.SetValueEx(h, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))
        winreg.SetValueEx(h, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(h, "NoRepair", 0, winreg.REG_DWORD, 1)


def install(
    options: InstallOptions,
    progress: Progress = lambda fraction, text: None,
    payload: Path | None = None,
) -> Path:
    """Copy the app, create shortcuts and registry entries.  Returns the exe."""
    payload = payload or payload_path()
    if not payload.is_file():
        raise SetupError("The installer is missing its application files.")
    directory = Path(options.directory).expanduser()
    exe = directory / EXE_NAME

    progress(0.0, "Preparing…")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SetupError(f"Cannot create {directory}:\n{error.strerror or error}") from error

    with zipfile.ZipFile(payload) as archive:
        members = archive.infolist()
        total = max(1, sum(m.file_size for m in members))
        done = 0
        for member in members:
            target = directory / member.filename
            if not str(target.resolve()).startswith(str(directory.resolve())):
                continue  # never write outside the install folder
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with archive.open(member) as source, open(target, "wb") as sink:
                    shutil.copyfileobj(source, sink, 1024 * 256)
            except PermissionError as error:
                raise SetupError(
                    "Lumina is currently running.\nClose it and try again."
                ) from error
            except OSError as error:
                raise SetupError(f"Could not write {target.name}:\n{error}") from error
            done += member.file_size
            progress(0.88 * done / total, f"Copying {member.filename.split('/')[-1]}")

    progress(0.90, "Creating shortcuts…")
    paths = shortcut_paths()
    if options.start_menu:
        _make_shortcut(paths["start_menu"], exe, directory)
    if options.desktop:
        _make_shortcut(paths["desktop"], exe, directory)

    progress(0.95, "Registering with Windows…")
    if options.associate:
        register_file_types(exe)
    _register_uninstall(directory, exe, total // 1024)
    progress(1.0, "Done")
    return exe


# -- uninstall ---------------------------------------------------------------
def _delete_tree(root: int, key: str) -> None:
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_ALL_ACCESS) as handle:
            while True:
                try:
                    child = winreg.EnumKey(handle, 0)
                except OSError:
                    break
                _delete_tree(root, rf"{key}\{child}")
        winreg.DeleteKey(root, key)
    except OSError:
        pass


def _delete_value(root: int, key: str, name: str) -> None:
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.DeleteValue(handle, name)
    except OSError:
        pass


def uninstall(
    directory: Path,
    remove_settings: bool = False,
    progress: Progress = lambda fraction, text: None,
) -> None:
    """Remove shortcuts, registry entries and (after we exit) the app folder."""
    progress(0.1, "Removing shortcuts…")
    for path in shortcut_paths().values():
        try:
            path.unlink()
        except OSError:
            pass

    progress(0.35, "Removing Windows registration…")
    hkcu = winreg.HKEY_CURRENT_USER
    for ext in ASSOC_EXTS:
        _delete_value(hkcu, rf"Software\Classes\{ext}\OpenWithProgids", PROG_ID)
    _delete_tree(hkcu, rf"Software\Classes\{PROG_ID}")
    _delete_tree(hkcu, rf"Software\Classes\Applications\{EXE_NAME}")
    _delete_value(hkcu, r"Software\RegisteredApplications", APP_NAME)
    _delete_tree(hkcu, CAPABILITIES_KEY)
    _delete_tree(hkcu, UNINSTALL_KEY)

    progress(0.6, "Cleaning up…")
    if remove_settings:
        _delete_tree(hkcu, r"Software\Lumina")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            shutil.rmtree(Path(local) / "Lumina", ignore_errors=True)
    _notify_shell()

    progress(1.0, "Done")


def schedule_folder_removal(directory: Path) -> None:
    """Delete *directory* once this process (which may live in it) has exited.

    Call it as the very last thing, right before quitting.
    """
    if not directory.exists():
        return
    # A throw-away batch file avoids cmd's awkward quoting rules.  It waits for
    # our process to exit (the app's own DLLs are locked until then), retries,
    # and finally deletes itself.
    import tempfile

    script = Path(tempfile.gettempdir()) / "lumina-uninstall-cleanup.bat"
    script.write_text(
        "@echo off\r\n"
        "ping -n 3 127.0.0.1 >nul\r\n"
        f'rmdir /s /q "{directory}"\r\n'
        f'if exist "{directory}" ping -n 4 127.0.0.1 >nul\r\n'
        f'if exist "{directory}" rmdir /s /q "{directory}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n',
        encoding="oem",  # what cmd.exe reads batch files as
        errors="replace",
    )
    subprocess.Popen(
        ["cmd", "/c", str(script)],
        creationflags=NO_WINDOW,
        close_fds=True,
    )


def open_default_apps_settings() -> None:
    """Jump to Windows' Default apps page for Lumina (user confirms there)."""
    for uri in (
        f"ms-settings:defaultapps?registeredAppUser={APP_NAME}",
        "ms-settings:defaultapps",
    ):
        try:
            os.startfile(uri)  # noqa: S606
            return
        except OSError:
            continue
