"""UpdateController against fake feed and install functions on real worker threads."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from detectorist import toasts as toasts_module
from detectorist.main import attach_updater
from detectorist.update import controller as update_controller
from detectorist.update import feed, install
from detectorist.update.controller import NO_INSTALL_REASON, UpdateController, UpdateState
from detectorist.update.download import DownloadCancelled
from detectorist.update.feed import DEFAULT_FEED_URL, Update, UpdateError
from detectorist.update.install import (
    AppInstall,
    LinuxAppInstall,
    MacOSAppInstall,
    UnixAppInstall,
    WindowsAppInstall,
)
from tests.update_helpers import UPDATE, RecordingWindow, linux_install, stop_worker_threads


@pytest.fixture
def window(qtbot):
    win = RecordingWindow()
    qtbot.addWidget(win)
    yield win
    stop_worker_threads(win)


def _feed(monkeypatch: pytest.MonkeyPatch, update: Update | None = UPDATE, error: str | None = None) -> list[str]:
    """Answer checks with update, or fail with error. Returns the URLs asked."""
    asked: list[str] = []

    def fetch(url: str) -> dict:
        asked.append(url)
        if error:
            raise UpdateError(error)
        return {}

    monkeypatch.setattr(feed, "fetch_latest_release", fetch)
    monkeypatch.setattr(feed, "find_update", lambda release, version, asset: update)
    return asked


def _controller(window, install: AppInstall | None) -> UpdateController:
    return UpdateController(window, "0.8.0", install, "https://feed", "a.AppImage")


def _titles(toasts) -> list[str]:
    return [title for _kind, title, _text, _kw in toasts]


def _link(toasts, index: int, label: str) -> Callable[[], None]:
    kwargs = toasts[index][3]
    assert kwargs.get("link_text") == label
    return kwargs["on_link"]


def _link_text(controller: UpdateController) -> str:
    return re.sub(r"<[^>]+>", "", controller.status_link.text())


def _record_dialogs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []

    class FakeDialog:
        def __init__(self, update, current_version, reason, parent) -> None:
            opened.append(update.version)

        def exec(self) -> bool:
            return False

    monkeypatch.setattr(update_controller, "UpdateDialog", FakeDialog)
    return opened


def _ready(controller: UpdateController, payload: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Put controller in READY with payload and return the payloads it applies."""
    applied: list[Path] = []
    monkeypatch.setattr(type(controller._install), "apply", lambda target, p: applied.append(p))
    controller._update = UPDATE
    controller._payload = payload
    controller._set_state(UpdateState.READY)
    return applied


def _start_download(controller: UpdateController, monkeypatch: pytest.MonkeyPatch, download) -> None:
    monkeypatch.setattr(LinuxAppInstall, "free_space_ok", lambda target, update: True)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda target, update: None)
    monkeypatch.setattr(install, "download", download)
    controller._update = UPDATE
    controller.start_download()


def test_startup_check_failure_shows_nothing(qtbot, window, monkeypatch, toasts) -> None:
    _feed(monkeypatch, error="offline")
    controller = _controller(window, None)
    controller.check()
    qtbot.waitUntil(lambda: controller.state is UpdateState.IDLE)
    assert toasts == []
    assert controller.status_link.isHidden()


def test_startup_check_with_update_shows_link_menu_text_and_toast(qtbot, window, monkeypatch, toasts, tmp_path) -> None:
    _feed(monkeypatch)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda target, update: None)
    controller = _controller(window, linux_install(tmp_path))
    controller.check()
    qtbot.waitUntil(lambda: controller.state is UpdateState.AVAILABLE and bool(toasts))
    assert not controller.status_link.isHidden()
    assert _link_text(controller) == "Update to 0.9.0"
    assert controller.action.text() == "Update to 0.9.0..."
    assert [(kind, title, text) for kind, title, text, _kw in toasts] == [
        ("information", "Update available", "Detectorist 0.9.0 is available.")
    ]
    assert _link(toasts, 0, "What's new")


def test_whats_new_link_opens_the_update_dialog(qtbot, window, monkeypatch, toasts) -> None:
    opened = _record_dialogs(monkeypatch)
    _feed(monkeypatch)
    controller = _controller(window, None)
    controller.check()
    qtbot.waitUntil(lambda: bool(toasts))
    _link(toasts, 0, "What's new")()
    assert opened == ["0.9.0"]


def test_clicking_the_status_link_opens_the_update_dialog(window, monkeypatch) -> None:
    opened = _record_dialogs(monkeypatch)
    controller = _controller(window, None)
    controller._update = UPDATE
    controller._set_state(UpdateState.AVAILABLE)
    controller.status_link.linkActivated.emit("#")
    assert opened == ["0.9.0"]


def test_manual_check_up_to_date_shows_toast(qtbot, window, monkeypatch, toasts) -> None:
    _feed(monkeypatch, update=None)
    controller = _controller(window, None)
    controller.check(manual=True)
    qtbot.waitUntil(lambda: controller.state is UpdateState.IDLE and bool(toasts))
    assert _titles(toasts) == ["You're up to date"]


def test_manual_check_failure_shows_error(qtbot, window, monkeypatch, toasts) -> None:
    _feed(monkeypatch, error="offline")
    controller = _controller(window, None)
    controller.check(manual=True)
    qtbot.waitUntil(lambda: controller.state is UpdateState.IDLE)
    assert [kind for kind, *_ in toasts] == ["error"]


def test_staged_payload_from_last_session_goes_straight_to_ready(qtbot, window, monkeypatch, toasts, tmp_path) -> None:
    staged = tmp_path / "stage" / "0.9.0" / "a.AppImage"
    _feed(monkeypatch)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda target, update: staged)
    window.show()
    controller = _controller(window, linux_install(tmp_path))
    controller.check()
    qtbot.waitUntil(lambda: controller.state is UpdateState.READY)
    assert _link_text(controller) == "Install and relaunch"
    # Announced as ready only, never first as merely available
    assert _titles(toasts) == ["Update ready"]
    applied: list = []
    monkeypatch.setattr(LinuxAppInstall, "apply", lambda target, payload: applied.append(payload))
    _link(toasts, 0, "Install and relaunch")()
    qtbot.waitUntil(lambda: window.closed)
    controller.apply_pending_update()
    assert applied == [staged]


def test_manual_check_with_a_staged_payload_offers_the_restart(qtbot, window, monkeypatch, tmp_path) -> None:
    staged = tmp_path / "stage" / "0.9.0" / "a.AppImage"
    _feed(monkeypatch)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda target, update: staged)
    monkeypatch.setattr(update_controller, "UpdateDialog", lambda *_a: pytest.fail("offered a staged download"))
    controller = _controller(window, linux_install(tmp_path))
    controller.check(manual=True)
    qtbot.waitUntil(lambda: controller.state is UpdateState.READY)


def test_staged_older_version_is_replaced_by_newer_release(qtbot, window, monkeypatch, tmp_path) -> None:
    (tmp_path / "stage" / "0.8.5").mkdir(parents=True)
    _feed(monkeypatch)
    controller = _controller(window, linux_install(tmp_path))
    controller.check()
    qtbot.waitUntil(lambda: controller.state is UpdateState.AVAILABLE and not (tmp_path / "stage" / "0.8.5").exists())
    assert controller.update == UPDATE


def test_a_blocked_install_skips_the_staged_lookup(qtbot, window, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(UnixAppInstall, "unwritable_reason", lambda self: self.move_hint)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda *_a: pytest.fail("looked for a staged update"))
    _feed(monkeypatch)
    controller = _controller(window, linux_install(tmp_path))
    controller.check()
    qtbot.waitUntil(lambda: controller.state is UpdateState.AVAILABLE)


def test_block_reasons(window, tmp_path, monkeypatch) -> None:
    assert _controller(window, None).block_reason() == NO_INSTALL_REASON
    mac = MacOSAppInstall(tmp_path / "Detectorist.app", tmp_path / "stage")
    monkeypatch.setattr(UnixAppInstall, "unwritable_reason", lambda self: self.move_hint)
    assert _controller(window, mac).block_reason() == MacOSAppInstall.move_hint
    assert _controller(window, linux_install(tmp_path)).block_reason() == LinuxAppInstall.move_hint
    monkeypatch.setattr(UnixAppInstall, "unwritable_reason", lambda self: None)
    assert _controller(window, linux_install(tmp_path)).block_reason() is None


def test_a_blocked_swap_explains_itself_once(window, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(UnixAppInstall, "unwritable_reason", lambda self: None)
    mac = MacOSAppInstall(tmp_path / "Detectorist.app", tmp_path / "stage")
    (tmp_path / "stage").mkdir()
    (tmp_path / "stage" / "apply-failed.txt").write_text("Operation not permitted")
    assert _controller(window, mac).block_reason() == MacOSAppInstall.apply_failed_reason
    assert _controller(window, mac).block_reason() is None


def test_download_without_space_shows_error(window, monkeypatch, toasts, tmp_path) -> None:
    monkeypatch.setattr(LinuxAppInstall, "free_space_ok", lambda target, update: False)
    controller = _controller(window, linux_install(tmp_path))
    controller._update = UPDATE
    controller.start_download()
    assert controller.state is not UpdateState.DOWNLOADING
    assert _titles(toasts) == ["Not enough disk space"]


def test_download_reaches_ready(qtbot, window, monkeypatch, toasts, tmp_path) -> None:
    monkeypatch.setattr(LinuxAppInstall, "prepare", lambda target, update, archive: archive)
    controller = _controller(window, linux_install(tmp_path))
    _start_download(controller, monkeypatch, lambda update, dest, progress, cancelled: progress(10, 10))
    qtbot.waitUntil(lambda: controller.state is UpdateState.READY)
    assert _titles(toasts) == ["Update ready"]
    assert _link(toasts, 0, "Install and relaunch")


def _on_ui_thread() -> bool:
    # A bool, never the QThread itself: stop_worker_threads quits every QThread
    # it finds, and a kept wrapper of the main thread would be among them
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    return QThread.currentThread() is QApplication.instance().thread()


def test_failed_download_is_handled_on_the_ui_thread(qtbot, window, monkeypatch, tmp_path) -> None:
    def mismatch(*_args) -> None:
        raise UpdateError("checksum mismatch")

    threads: list[bool] = []
    monkeypatch.setattr(toasts_module, "show_error_toast", lambda *_a, **_kw: threads.append(_on_ui_thread()))
    controller = _controller(window, linux_install(tmp_path))
    _start_download(controller, monkeypatch, mismatch)
    qtbot.waitUntil(lambda: controller.state is UpdateState.AVAILABLE and bool(threads))
    assert threads == [True]


def test_cancelled_download_returns_to_available_on_the_ui_thread(qtbot, window, monkeypatch, tmp_path) -> None:
    def cancelled(*_args) -> None:
        raise DownloadCancelled

    seen: list = []
    set_state = UpdateController._set_state

    def recording_set_state(self, state: UpdateState) -> None:
        seen.append((state, _on_ui_thread()))
        set_state(self, state)

    monkeypatch.setattr(UpdateController, "_set_state", recording_set_state)
    controller = _controller(window, linux_install(tmp_path))
    _start_download(controller, monkeypatch, cancelled)
    qtbot.waitUntil(lambda: controller.state is UpdateState.AVAILABLE)
    assert seen[-1] == (UpdateState.AVAILABLE, True)


def test_restart_declined_keeps_app_open_and_applies_nothing(window, monkeypatch, tmp_path) -> None:
    controller = _controller(window, linux_install(tmp_path))
    applied = _ready(controller, tmp_path / "payload", monkeypatch)
    window.show()
    window.refuse_close = True
    controller.request_restart()
    assert window.isVisible()
    controller.apply_pending_update()
    assert applied == []


def test_restart_accepted_applies_after_exit(qtbot, window, monkeypatch, tmp_path) -> None:
    controller = _controller(window, linux_install(tmp_path))
    applied = _ready(controller, tmp_path / "payload", monkeypatch)
    window.show()
    controller.request_restart()
    qtbot.waitUntil(lambda: window.closed)
    controller.apply_pending_update()
    assert applied == [tmp_path / "payload"]


def test_restart_waits_for_other_instances_on_windows(window, monkeypatch, toasts, tmp_path) -> None:
    """With a second instance running, Setup would wait 60 s and quit silently."""
    from detectorist import running_mutex

    monkeypatch.setattr(running_mutex, "other_instance_running", lambda: True)
    controller = _controller(window, WindowsAppInstall(tmp_path / "Detectorist", tmp_path / "t"))
    applied = _ready(controller, tmp_path / "setup.exe", monkeypatch)
    window.show()
    controller.request_restart()
    assert window.isVisible()
    controller.apply_pending_update()
    assert applied == []
    assert [(kind, title) for kind, title, _text, _kw in toasts] == [("error", "Detectorist is open twice")]


@pytest.fixture
def app_window(make_window):
    win = make_window()
    yield win
    stop_worker_threads(win)


def test_attach_updater_places_the_action_and_link(app_window) -> None:
    controller = attach_updater(app_window, compiled=False)
    texts = [a.text() for a in app_window.ui.menu_help.actions()]
    assert texts.index("Check for Updates...") < texts.index(app_window.ui.about_action.text())
    assert controller.status_link.parent() is app_window.ui.status_bar
    assert controller.block_reason() == NO_INSTALL_REASON


@pytest.mark.parametrize("override", [None, "http://localhost:8000/release.json"])
def test_attach_updater_asks_the_feed_url(qtbot, app_window, monkeypatch, override: str | None) -> None:
    if override is None:
        monkeypatch.delenv("DETECTORIST_UPDATE_FEED_URL", raising=False)
    else:
        monkeypatch.setenv("DETECTORIST_UPDATE_FEED_URL", override)
    asked = _feed(monkeypatch, update=None)
    controller = attach_updater(app_window, compiled=False)
    controller.check()
    qtbot.waitUntil(lambda: controller.state is UpdateState.IDLE)
    assert asked == [override or DEFAULT_FEED_URL]
