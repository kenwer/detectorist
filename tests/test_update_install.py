import shutil
import sys
from collections import namedtuple
from pathlib import Path

import pytest

from detectorist.update import install
from detectorist.update.feed import Update, UpdateError
from detectorist.update.install import (
    LinuxAppInstall,
    MacOSAppInstall,
    WindowsAppInstall,
    detect_install,
)
from tests.update_helpers import never, no_progress


def make_update(version: str = "0.9.0", size: int = 1000, sha256: str = "0" * 64, asset: str = "a.bin") -> Update:
    return Update(version, "", "", asset, "http://example.invalid/a.bin", size, sha256)


def test_windows_target_is_the_executable_folder(tmp_path: Path) -> None:
    exe = tmp_path / "Detectorist" / "Detectorist.exe"
    exe.parent.mkdir()
    (exe.parent / "unins000.exe").write_bytes(b"MZ")
    target = detect_install("win32", exe, {"TEMP": str(tmp_path / "t")})
    assert target == WindowsAppInstall(tmp_path / "Detectorist", tmp_path / "t" / "detectorist-update")


def test_macos_target_is_the_enclosing_app(tmp_path: Path) -> None:
    exe = tmp_path / "Apps" / "Detectorist.app" / "Contents" / "MacOS" / "Detectorist"
    target = detect_install("darwin", exe, {})
    assert target == MacOSAppInstall(tmp_path / "Apps" / "Detectorist.app", tmp_path / "Apps" / ".detectorist-update"
    )


def test_macos_without_an_app_bundle_has_no_target(tmp_path: Path) -> None:
    assert detect_install("darwin", tmp_path / "bin" / "python", {}) is None


def test_linux_target_is_the_appimage(tmp_path: Path) -> None:
    appimage = tmp_path / "Detectorist.AppImage"
    target = detect_install("linux", Path("/tmp/.mount_x/Detectorist"), {"APPIMAGE": str(appimage)})
    assert target == LinuxAppInstall(appimage, tmp_path / ".detectorist-update")


def test_linux_without_appimage_has_no_target(tmp_path: Path) -> None:
    assert detect_install("linux", tmp_path / "Detectorist", {}) is None


def test_writable_folder_is_writable(tmp_path: Path) -> None:
    app = tmp_path / "Detectorist.app"
    app.mkdir()
    assert MacOSAppInstall(app, tmp_path / ".detectorist-update").unwritable_reason() is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_read_only_folder_asks_to_move_the_app(tmp_path: Path) -> None:
    folder = tmp_path / "ro"
    (folder / "Detectorist.app").mkdir(parents=True)
    folder.chmod(0o500)
    try:
        mac = MacOSAppInstall(folder / "Detectorist.app", folder / ".detectorist-update")
        linux = LinuxAppInstall(folder / "Detectorist.AppImage", folder / ".detectorist-update")
        assert mac.unwritable_reason() == "Move Detectorist into the Applications folder, then check again."
        assert linux.unwritable_reason() == "Move the AppImage to a folder you can write to, then check again."
    finally:
        folder.chmod(0o700)


def test_windows_is_never_unwritable(tmp_path: Path) -> None:
    """Setup elevates by itself, so a folder the user cannot write to is no reason to block."""
    assert WindowsAppInstall(tmp_path / "missing", tmp_path / "t").unwritable_reason() is None


def test_only_the_macos_apply_failure_points_to_app_management(tmp_path: Path) -> None:
    assert "App Management" in MacOSAppInstall(tmp_path / "a.app", tmp_path).apply_failed_reason
    assert "App Management" not in LinuxAppInstall(tmp_path / "a.AppImage", tmp_path).apply_failed_reason


def test_version_dir_is_per_version(tmp_path: Path) -> None:
    target = LinuxAppInstall(tmp_path / "a.AppImage", tmp_path / "stage")
    assert target.version_dir(make_update("0.9.0")) == tmp_path / "stage" / "0.9.0"


def test_free_space_needs_two_and_a_half_times_the_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = LinuxAppInstall(tmp_path / "a.AppImage", tmp_path / "stage")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(install.shutil, "disk_usage", lambda _p: usage(0, 0, 2500))
    assert target.free_space_ok(make_update(size=1000))
    monkeypatch.setattr(install.shutil, "disk_usage", lambda _p: usage(0, 0, 2499))
    assert not target.free_space_ok(make_update(size=1000))


def test_cleanup_removes_applied_and_older_staged_versions_and_old_app(tmp_path: Path) -> None:
    app = tmp_path / "Detectorist.app"
    app.mkdir()
    (tmp_path / "Detectorist.app.old" / "Contents").mkdir(parents=True)
    stage = tmp_path / ".detectorist-update"
    for version in ("0.8.0", "0.9.0", "0.10.0", "not-a-version"):
        (stage / version).mkdir(parents=True)
    MacOSAppInstall(app, stage).cleanup("0.9.0")
    assert sorted(p.name for p in stage.iterdir()) == ["0.10.0", "not-a-version"]
    assert not (tmp_path / "Detectorist.app.old").exists()
    assert app.is_dir()


def test_cleanup_removes_an_old_appimage(tmp_path: Path) -> None:
    appimage = tmp_path / "Detectorist.AppImage"
    appimage.write_bytes(b"new")
    (tmp_path / "Detectorist.AppImage.old").write_bytes(b"old")
    LinuxAppInstall(appimage, tmp_path / ".detectorist-update").cleanup("0.9.0")
    assert not (tmp_path / "Detectorist.AppImage.old").exists()


def test_cleanup_without_staging_is_a_no_op(tmp_path: Path) -> None:
    WindowsAppInstall(tmp_path / "app", tmp_path / "missing").cleanup("0.9.0")


def test_prepare_linux_makes_the_appimage_executable(tmp_path: Path) -> None:
    archive = tmp_path / "0.9.0" / "Detectorist-linux-x86_64.AppImage"
    archive.parent.mkdir()
    archive.write_bytes(b"elf")
    target = LinuxAppInstall(tmp_path / "Detectorist.AppImage", tmp_path)
    assert target.prepare(make_update(), archive) == archive
    if sys.platform != "win32":
        assert archive.stat().st_mode & 0o111


def test_prepare_windows_returns_the_installer(tmp_path: Path) -> None:
    setup = tmp_path / "setup.exe"
    setup.write_bytes(b"MZ")
    assert WindowsAppInstall(tmp_path / "app", tmp_path).prepare(make_update(), setup) == setup


def _fake_dmg(tmp_path: Path, version: str) -> Path:
    import plistlib
    import subprocess

    src = tmp_path / "src"
    contents = src / "Detectorist.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "Detectorist").write_text("#!/bin/sh\n")
    (contents / "Resources").mkdir()
    (contents / "MacOS" / "models").symlink_to("../Resources")
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleShortVersionString": version, "CFBundleExecutable": "Detectorist"}, f)
    dmg = tmp_path / "x.dmg"
    subprocess.run(["hdiutil", "create", "-srcfolder", str(src), "-ov", "-quiet", str(dmg)], check=True)
    return dmg


@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil")
def test_prepare_macos_extracts_and_checks_the_bundle(tmp_path: Path) -> None:
    target = MacOSAppInstall(tmp_path / "Apps" / "Detectorist.app", tmp_path / "stage")
    update = make_update("0.9.0")
    archive = target.version_dir(update) / "x.dmg"
    archive.parent.mkdir(parents=True)
    shutil.move(_fake_dmg(tmp_path, "0.9.0"), archive)
    app = target.prepare(update, archive)
    assert app == target.version_dir(update) / "Detectorist.app"
    assert (app / "Contents" / "MacOS" / "models").is_symlink()


@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil")
def test_prepare_macos_rejects_a_bundle_of_another_version(tmp_path: Path) -> None:
    target = MacOSAppInstall(tmp_path / "Apps" / "Detectorist.app", tmp_path / "stage")
    update = make_update("0.9.0")
    archive = target.version_dir(update) / "x.dmg"
    archive.parent.mkdir(parents=True)
    shutil.move(_fake_dmg(tmp_path, "0.8.0"), archive)
    with pytest.raises(UpdateError):
        target.prepare(update, archive)


def test_staged_payload_rechecks_the_digest(tmp_path: Path) -> None:
    import hashlib

    target = LinuxAppInstall(tmp_path / "Detectorist.AppImage", tmp_path / "stage")
    update = make_update(sha256=hashlib.sha256(b"payload").hexdigest(), asset="new.AppImage")
    dest = target.version_dir(update) / "new.AppImage"
    assert target.staged_payload(update) is None
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"payload")
    assert target.staged_payload(update) == dest
    dest.write_bytes(b"tampered")
    assert target.staged_payload(update) is None


class Recorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> None:
        self.commands.append(command)


def _bundle(path: Path, marker: str) -> Path:
    path.mkdir(parents=True)
    (path / "marker").write_text(marker)
    return path


def test_windows_starts_the_installer_silently_with_relaunch(tmp_path: Path) -> None:
    launch = Recorder()
    setup = tmp_path / "setup.exe"
    WindowsAppInstall(tmp_path / "Detectorist", tmp_path).apply(setup, launch)
    assert launch.commands == [[str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/RELAUNCH"]]


def test_macos_swaps_the_bundle_and_opens_the_new_one(tmp_path: Path) -> None:
    apps = tmp_path / "My Apps"
    app = _bundle(apps / "Detectorist.app", "old")
    payload = _bundle(apps / ".detectorist-update" / "0.9.0" / "Detectorist.app", "new")
    launch = Recorder()
    MacOSAppInstall(app, apps / ".detectorist-update").apply(payload, launch)
    assert (app / "marker").read_text() == "new"
    assert (apps / "Detectorist.app.old" / "marker").read_text() == "old"
    assert launch.commands == [["open", "-n", str(app)]]


def test_linux_swaps_the_appimage_and_starts_it(tmp_path: Path) -> None:
    appimage = tmp_path / "Detectorist.AppImage"
    appimage.write_text("old")
    payload = tmp_path / ".detectorist-update" / "0.9.0" / "Detectorist-linux-x86_64.AppImage"
    payload.parent.mkdir(parents=True)
    payload.write_text("new")
    launch = Recorder()
    LinuxAppInstall(appimage, tmp_path / ".detectorist-update").apply(payload, launch)
    assert appimage.read_text() == "new"
    assert (tmp_path / "Detectorist.AppImage.old").read_text() == "old"
    assert launch.commands == [[str(appimage)]]


def test_a_leftover_old_copy_is_replaced(tmp_path: Path) -> None:
    app = _bundle(tmp_path / "Detectorist.app", "current")
    _bundle(tmp_path / "Detectorist.app.old", "older")
    payload = _bundle(tmp_path / "stage" / "0.9.0" / "Detectorist.app", "new")
    MacOSAppInstall(app, tmp_path / "stage").apply(payload, Recorder())
    assert (tmp_path / "Detectorist.app.old" / "marker").read_text() == "current"
    assert (app / "marker").read_text() == "new"


def test_failed_swap_restores_and_restarts_the_old_app(tmp_path: Path) -> None:
    app = _bundle(tmp_path / "Detectorist.app", "old")
    launch = Recorder()
    MacOSAppInstall(app, tmp_path / "stage").apply(tmp_path / "stage" / "missing.app", launch)
    assert (app / "marker").read_text() == "old"
    assert not (tmp_path / "Detectorist.app.old").exists()
    assert launch.commands == [["open", "-n", str(app)]]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_failed_first_rename_restarts_the_old_app(tmp_path: Path) -> None:
    folder = tmp_path / "ro"
    appimage = folder / "Detectorist.AppImage"
    folder.mkdir()
    appimage.write_text("old")
    payload = tmp_path / "new.AppImage"
    payload.write_text("new")
    folder.chmod(0o500)
    launch = Recorder()
    try:
        LinuxAppInstall(appimage, tmp_path / "stage").apply(payload, launch)
    finally:
        folder.chmod(0o700)
    assert appimage.read_text() == "old"
    assert launch.commands == [[str(appimage)]]


def _staged_macos(tmp_path: Path, plist_version: str | None) -> tuple[MacOSAppInstall, Update]:
    import hashlib
    import plistlib

    target = MacOSAppInstall(tmp_path / "Detectorist.app", tmp_path / "stage")
    update = make_update("0.9.0", sha256=hashlib.sha256(b"dmg").hexdigest(), asset="x.dmg")
    vdir = target.version_dir(update)
    vdir.mkdir(parents=True)
    (vdir / "x.dmg").write_bytes(b"dmg")
    contents = vdir / "Detectorist.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "Detectorist").write_text("bin")
    if plist_version is not None:
        with (contents / "Info.plist").open("wb") as f:
            plistlib.dump({"CFBundleShortVersionString": plist_version, "CFBundleExecutable": "Detectorist"}, f)
    return target, update


@pytest.mark.parametrize("plist_version", ["0.8.0", None], ids=["other-version", "half-extracted"])
def test_a_staged_bundle_that_fails_the_check_is_extracted_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plist_version: str | None
) -> None:
    target, update = _staged_macos(tmp_path, plist_version)
    extracted: list[Path] = []

    def failing_extract(dmg: Path, _dest: Path) -> None:
        extracted.append(dmg)
        raise UpdateError("unpack failed")

    monkeypatch.setattr(install, "_extract_bundle", failing_extract)
    with pytest.raises(UpdateError):
        target.staged_payload(update)
    assert extracted == [target.archive_path(update)]
    assert not (target.version_dir(update) / "Detectorist.app").exists()


def test_staged_payload_accepts_a_checked_bundle(tmp_path: Path) -> None:
    target, update = _staged_macos(tmp_path, "0.9.0")
    assert target.staged_payload(update) == target.version_dir(update) / "Detectorist.app"


def test_a_bundle_without_its_executable_fails_the_check(tmp_path: Path) -> None:
    target, update = _staged_macos(tmp_path, "0.9.0")
    (target.version_dir(update) / "Detectorist.app" / "Contents" / "MacOS" / "Detectorist").unlink()
    with pytest.raises(UpdateError, match="executable is missing"):
        install._check_bundle(target.version_dir(update) / "Detectorist.app", "0.9.0")


@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil")
def test_rejected_bundle_is_not_left_where_it_could_be_installed(tmp_path: Path) -> None:
    target = MacOSAppInstall(tmp_path / "Apps" / "Detectorist.app", tmp_path / "stage")
    update = make_update("0.9.0")
    archive = target.version_dir(update) / "x.dmg"
    archive.parent.mkdir(parents=True)
    shutil.move(_fake_dmg(tmp_path, "0.8.0"), archive)
    with pytest.raises(UpdateError):
        target.prepare(update, archive)
    assert sorted(p.name for p in target.version_dir(update).iterdir()) == ["x.dmg"]


def test_a_failed_swap_leaves_a_note_for_the_next_session(tmp_path: Path) -> None:
    app = _bundle(tmp_path / "Detectorist.app", "old")
    target = MacOSAppInstall(app, tmp_path / "stage")
    target.apply(tmp_path / "stage" / "missing.app", Recorder())
    assert target.take_apply_failure()
    assert not target.take_apply_failure()


def test_a_successful_swap_leaves_no_note(tmp_path: Path) -> None:
    app = _bundle(tmp_path / "Detectorist.app", "old")
    payload = _bundle(tmp_path / "stage" / "0.9.0" / "Detectorist.app", "new")
    target = MacOSAppInstall(app, tmp_path / "stage")
    target.apply(payload, Recorder())
    assert not target.take_apply_failure()


def test_verified_archive_checks_the_digest(tmp_path: Path) -> None:
    import hashlib

    target = MacOSAppInstall(tmp_path / "Detectorist.app", tmp_path / "stage")
    update = make_update(sha256=hashlib.sha256(b"dmg").hexdigest(), asset="x.dmg")
    assert target.verified_archive(update) is None
    archive = target.version_dir(update) / "x.dmg"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"dmg")
    assert target.verified_archive(update) == archive
    archive.write_bytes(b"bad")
    assert target.verified_archive(update) is None


def test_a_failed_launch_is_logged_not_raised(tmp_path: Path) -> None:
    """setup.exe removed by a TEMP cleaner must not crash the exit."""
    def missing(command: list[str]) -> None:
        raise FileNotFoundError(command[0])

    target = WindowsAppInstall(tmp_path / "Detectorist", tmp_path / "t")
    target.apply(tmp_path / "t" / "0.9.0" / "setup.exe", missing)
    assert target.take_apply_failure()


def test_windows_target_needs_the_installers_uninstaller(tmp_path: Path) -> None:
    """An exe outside the installed folder cannot be updated by Setup."""
    exe = tmp_path / "copy" / "Detectorist.exe"
    exe.parent.mkdir()
    assert detect_install("win32", exe, {"TEMP": str(tmp_path)}) is None


def _linux_target(tmp_path: Path) -> LinuxAppInstall:
    return LinuxAppInstall(tmp_path / "Detectorist.AppImage", tmp_path / "stage")


def test_fetch_reuses_a_staged_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    staged = tmp_path / "stage" / "0.9.0" / "a.bin"
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda target, update: staged)
    monkeypatch.setattr(install, "download", lambda *a: pytest.fail("downloaded again"))
    assert _linux_target(tmp_path).fetch_payload(make_update(), no_progress, never) == staged


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_staged_appimage_is_made_executable(tmp_path: Path) -> None:
    """Covers a quit between the download's rename and its chmod."""
    import hashlib

    target = _linux_target(tmp_path)
    update = make_update(sha256=hashlib.sha256(b"elf").hexdigest())
    archive = target.archive_path(update)
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"elf")
    archive.chmod(0o644)
    assert target.staged_payload(update) == archive
    assert archive.stat().st_mode & 0o111


def test_staged_payload_is_none_without_a_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(install, "download", lambda *a: pytest.fail("downloaded without a click"))
    assert _linux_target(tmp_path).staged_payload(make_update()) is None


def test_staged_payload_removes_other_staged_versions(tmp_path: Path) -> None:
    (tmp_path / "stage" / "0.8.5").mkdir(parents=True)
    (tmp_path / "stage" / "0.9.0").mkdir()
    _linux_target(tmp_path).staged_payload(make_update())
    assert [p.name for p in (tmp_path / "stage").iterdir()] == ["0.9.0"]


def test_fetch_downloads_into_the_version_dir_and_prepares(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    downloaded: list[Path] = []
    monkeypatch.setattr(install, "download", lambda update, dest, *_a: downloaded.append(dest))
    monkeypatch.setattr(LinuxAppInstall, "prepare", lambda target, update, archive: archive)
    payload = _linux_target(tmp_path).fetch_payload(make_update(), no_progress, never)
    assert downloaded == [tmp_path / "stage" / "0.9.0" / "a.bin"]
    assert payload == downloaded[0]


def test_staged_payload_prepares_a_verified_archive_again(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The DMG is intact but its extracted .app went missing."""
    archive = tmp_path / "stage" / "0.9.0" / "a.bin"
    prepared: list[Path] = []
    monkeypatch.setattr(MacOSAppInstall, "verified_archive", lambda target, update: archive)
    monkeypatch.setattr(install, "download", lambda *a: pytest.fail("downloaded again"))
    monkeypatch.setattr(MacOSAppInstall, "prepare", lambda target, update, a: prepared.append(a) or a)
    mac = MacOSAppInstall(tmp_path / "Detectorist.app", tmp_path / "stage")
    payload = mac.staged_payload(make_update())
    assert prepared == [archive]
    assert payload == archive


def test_a_failed_dmg_mount_reads_as_update_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The toast shows hdiutil's own message, not a CalledProcessError repr."""
    import subprocess

    def failing_run(command, **_kw):
        raise subprocess.CalledProcessError(1, command, stderr=b"hdiutil: attach failed - image not recognized")

    monkeypatch.setattr(install.subprocess, "run", failing_run)
    mac = MacOSAppInstall(tmp_path / "Detectorist.app", tmp_path / "stage")
    update = make_update(asset="x.dmg")
    with pytest.raises(UpdateError, match="image not recognized"):
        mac.prepare(update, mac.archive_path(update))
    assert not (mac.version_dir(update) / "Detectorist.app.partial").exists()
