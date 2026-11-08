"""Where the app is installed, and staging, preparing and applying an update.

macOS and Linux stage next to the app, so applying is a rename on one volume.
Windows stages in %TEMP%, since the installer copies the files anyway.
"""

import contextlib
import logging
import os
import plistlib
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from packaging.version import InvalidVersion, Version

from detectorist import running_mutex

from .download import download, sha256_of
from .feed import Update, UpdateError

_log = logging.getLogger(__name__)

STAGING_DIR_NAME = ".detectorist-update"
# Written when apply could not swap the app, read by the next session
_APPLY_FAILED = "apply-failed.txt"
# An update needs room for the download, an extracted copy and the old version
_FREE_SPACE_FACTOR = 2.5
_APP_BUNDLE = "Detectorist.app"

Launcher = Callable[[list[str]], None]
Progress = Callable[[int, int], None]


def required_space(update: Update) -> int:
    return int(_FREE_SPACE_FACTOR * update.size)


@dataclass(frozen=True)
class AppInstall(ABC):
    """An installed copy of the app that can update itself."""

    app_path: Path
    staging_dir: Path

    apply_failed_reason: ClassVar[str] = "The last update could not replace the app. Install the new version from the download page."

    def unwritable_reason(self) -> str | None:
        """Why the app cannot be replaced in place, or None when it can."""
        return None

    def restart_blocker(self) -> tuple[str, str] | None:
        """A title and text for why the update cannot be applied right now, or None."""
        return None

    @abstractmethod
    def apply(self, payload: Path, launch: Launcher | None = None) -> None:
        """Install payload and start the new version. Called while the app exits.

        Never raises, the caller is shutting down. A failure is logged and
        left for take_apply_failure in the next session.
        """

    def version_dir(self, update: Update) -> Path:
        return self.staging_dir / update.version

    def archive_path(self, update: Update) -> Path:
        return self.version_dir(update) / update.asset_name

    def free_space_ok(self, update: Update) -> bool:
        folder = self.staging_dir if self.staging_dir.exists() else self.staging_dir.parent
        return shutil.disk_usage(folder).free >= required_space(update)

    def prepare(self, update: Update, archive: Path) -> Path:
        """Turn the verified download into what apply installs from.

        Cheap when an earlier call already did the work, so a staged update is
        prepared again instead of asking whether it was.
        """
        return archive

    def verified_archive(self, update: Update) -> Path | None:
        """The downloaded file from an earlier session, if it still matches the digest."""
        archive = self.archive_path(update)
        if not archive.is_file() or sha256_of(archive) != update.sha256:
            return None
        return archive

    def staged_payload(self, update: Update) -> Path | None:
        """The payload staged for update by an earlier session, or None.

        Staged versions other than update's are deleted first.
        """
        self._prune_staged(keep=lambda name: name == update.version)
        archive = self.verified_archive(update)
        return None if archive is None else self.prepare(update, archive)

    def fetch_payload(self, update: Update, progress: Progress, cancelled: Callable[[], bool]) -> Path:
        """The payload apply installs, from an earlier session or downloaded now."""
        payload = self.staged_payload(update)
        if payload is not None:
            return payload
        archive = self.archive_path(update)
        download(update, archive, progress, cancelled)
        return self.prepare(update, archive)

    def cleanup(self, current_version: str) -> None:
        """Delete staged versions up to current_version. Runs at startup.

        A staged version newer than the running one is kept, so a downloaded
        update survives a normal quit. Errors are logged, not raised.
        """
        try:
            running = Version(current_version)
        except InvalidVersion:
            return

        def newer(name: str) -> bool:
            try:
                return Version(name) > running
            except InvalidVersion:
                return True

        self._prune_staged(keep=newer)

    def take_apply_failure(self) -> bool:
        """Whether the last apply failed. The note is deleted once read.

        Read once, so one session explains the failure and the next tries again,
        in case the user has since granted the permission that was missing.
        """
        try:
            (self.staging_dir / _APPLY_FAILED).unlink()
        except OSError:
            return False
        return True

    def _prune_staged(self, keep: Callable[[str], bool]) -> None:
        try:
            entries = list(self.staging_dir.iterdir())
        except OSError:
            return  # nothing staged yet, or unreadable, which cleanup must not raise
        for staged in entries:
            if staged.is_dir() and not keep(staged.name):
                _log.info("removing staged update %s", staged)
                _remove(staged)

    def _note_failure(self, exc: OSError) -> None:
        try:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            (self.staging_dir / _APPLY_FAILED).write_text(str(exc), encoding="utf-8")
        except OSError:
            pass  # the caller's log line still records it

    def _launch_logged(self, launch: Launcher, command: list[str]) -> None:
        # The app is exiting, so a failed start, say setup.exe removed from %TEMP%,
        # is logged and noted for the next session instead of raised
        try:
            launch(command)
        except OSError as exc:
            _log.error("could not start %s: %s", command[0], exc)
            self._note_failure(exc)


class WindowsAppInstall(AppInstall):
    """The folder Setup installed into. Setup itself elevates, so it is never unwritable."""

    def restart_blocker(self) -> tuple[str, str] | None:
        if running_mutex.other_instance_running():
            # Setup would wait for that instance, give up after 60 s and leave no trace
            return (
                "Detectorist is open twice",
                "Close the other Detectorist window, then select Install and relaunch again.",
            )
        return None

    def apply(self, payload: Path, launch: Launcher | None = None) -> None:
        """Hand over to Setup, which waits for this process through the running mutex."""
        self._launch_logged(launch or _launch_detached, [str(payload), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/RELAUNCH"])


class UnixAppInstall(AppInstall):
    """An app replaced by renaming, which macOS and Linux allow while it runs."""

    move_hint: ClassVar[str]

    @abstractmethod
    def start_command(self) -> list[str]: ...

    @property
    def old_path(self) -> Path:
        """Where apply moves the running app aside."""
        return self.app_path.with_name(self.app_path.name + ".old")

    def unwritable_reason(self) -> str | None:
        return None if os.access(self.app_path.parent, os.W_OK) else self.move_hint

    def cleanup(self, current_version: str) -> None:
        _remove(self.old_path)
        super().cleanup(current_version)

    def apply(self, payload: Path, launch: Launcher | None = None) -> None:
        """Rename the running app aside and the new one into place.

        A failed rename puts the old app back, which is then started again.
        """
        app, old = self.app_path, self.old_path
        _remove(old)
        try:
            app.rename(old)
            payload.rename(app)
        except OSError as exc:
            _log.error("could not install the update from %s: %s", payload, exc)
            self._note_failure(exc)
            if old.exists() and not app.exists():
                try:
                    old.rename(app)
                except OSError as restore_exc:
                    _log.error("could not restore %s: %s", app, restore_exc)
        self._launch_logged(launch or _launch_detached, self.start_command())


class MacOSAppInstall(UnixAppInstall):
    """The .app bundle, updated from the bundle inside the release DMG."""

    move_hint = "Move Detectorist into the Applications folder, then check again."
    apply_failed_reason: ClassVar[str] = (
        "macOS blocked the last update. Allow Detectorist under System Settings > "
        "Privacy & Security > App Management and check again, or install the new "
        "version from the download page."
    )

    def start_command(self) -> list[str]:
        return ["open", "-n", str(self.app_path)]

    def prepare(self, update: Update, archive: Path) -> Path:
        app = self.version_dir(update) / _APP_BUNDLE
        with contextlib.suppress(UpdateError):
            _check_bundle(app, update.version)
            return app
        # Extracted and checked under another name, so a failed or interrupted
        # copy never sits where the check above and apply look
        partial = app.with_name(_APP_BUNDLE + ".partial")
        for stale in (app, partial):
            if stale.exists():
                shutil.rmtree(stale)
        try:
            _extract_bundle(archive, partial)
            _check_bundle(partial, update.version)
            partial.rename(app)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        return app


class LinuxAppInstall(UnixAppInstall):
    """The AppImage file, replaced by the downloaded one."""

    move_hint = "Move the AppImage to a folder you can write to, then check again."

    def start_command(self) -> list[str]:
        return [str(self.app_path)]

    def prepare(self, update: Update, archive: Path) -> Path:
        archive.chmod(0o755)
        return archive


def detect_install(system: str, executable: Path, environ: Mapping[str, str]) -> AppInstall | None:
    """The installed app around executable, or None where an in-app install cannot work."""
    if system == "win32":
        # Setup installs into its own folder, so only a copy it installed can be updated
        if not (executable.parent / "unins000.exe").is_file():
            return None
        temp = environ.get("TEMP") or tempfile.gettempdir()
        return WindowsAppInstall(executable.parent, Path(temp) / "detectorist-update")
    if system == "darwin":
        app = next((p for p in executable.parents if p.suffix == ".app"), None)
        if app is None:
            return None
        return MacOSAppInstall(app, app.parent / STAGING_DIR_NAME)
    appimage = environ.get("APPIMAGE")
    if not appimage:
        return None
    path = Path(appimage)
    return LinuxAppInstall(path, path.parent / STAGING_DIR_NAME)


def _remove(path: Path) -> None:
    """Delete a file or a folder tree. What cannot be removed is logged."""

    def warn(_fn: object, failed: str | Path, exc: BaseException) -> None:
        _log.warning("could not remove %s: %s", failed, exc)

    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onexc=warn)
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        warn(None, path, exc)


def _extract_bundle(dmg: Path, dest: Path) -> None:
    try:
        with tempfile.TemporaryDirectory() as mount:
            subprocess.run(
                ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, str(dmg)],
                check=True,
                capture_output=True,
            )
            try:
                # ditto keeps the bundle's symlinks and its ad-hoc signature
                subprocess.run(["ditto", str(Path(mount) / _APP_BUNDLE), str(dest)], check=True, capture_output=True)
            finally:
                subprocess.run(["hdiutil", "detach", mount], check=False, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip() if exc.stderr else ""
        raise UpdateError(f"Could not unpack the downloaded update: {detail or exc}") from exc


def _check_bundle(app: Path, version: str) -> None:
    try:
        with (app / "Contents" / "Info.plist").open("rb") as f:
            info = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise UpdateError(f"The downloaded app is incomplete: {exc}") from exc
    found = info.get("CFBundleShortVersionString")
    if found != version:
        raise UpdateError(f"The downloaded app is version {found}, expected {version}.")
    # The binary is named by the bundle itself, so a renamed build output still passes
    executable = str(info.get("CFBundleExecutable", ""))
    if not executable or not (app / "Contents" / "MacOS" / executable).is_file():
        raise UpdateError("The downloaded app is incomplete: its executable is missing.")


def _launch_detached(command: list[str]) -> None:
    """Start command so that it outlives this process."""
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)  # noqa: S603  the command is built from our own paths
