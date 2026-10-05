"""Shared fixtures.

qtbot and qapp come from pytest-qt. The offscreen platform is forced so a
developer machine and headless CI behave the same.
"""

import json
import os
import shutil
import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt, QUrl
from PySide6.QtTest import QTest

from detectorist import model_downloader
from detectorist import toasts as toasts_module
from detectorist.model_downloader import ModelDownloader
from detectorist.settings import Settings
from tests.fakes import FakeDetectorFactory
from tests.tiny_models import DETECT_MODEL

# Assigned, not setdefault: on a real platform the window tests would open
# windows and the clipboard tests would overwrite the developer's clipboard.
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(autouse=True)
def toasts(monkeypatch) -> list[tuple[str, str, str, dict]]:
    """Record (kind, title, text, kwargs) per toast instead of showing one.

    kind is the preset name in lower case ("success", "error", "warning"). A
    real pyqttoast keeps class-level queues and timers alive past the test.
    """
    shown: list[tuple[str, str, str, dict]] = []

    def record(_parent, title, text, preset, **kwargs):
        shown.append((preset.name.lower(), title, text, kwargs))

    monkeypatch.setattr(toasts_module, "_show_toast", record)
    return shown


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, tmp_path) -> None:
    """Point the manifest URL at a missing local file.

    A test that forgets to set up its own manifest then gets a quick local
    error instead of a request to GitHub. Only the manifest fetch is covered:
    a test that starts a model download must supply its own local URLs.
    """
    missing = QUrl.fromLocalFile(str(tmp_path / "no-manifest.json")).toString()
    monkeypatch.setattr(model_downloader, "MANIFEST_URL", missing)


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / "settings.ini"


@pytest.fixture
def settings(qapp, settings_file) -> Settings:
    """A Settings backed by an INI file in tmp_path.

    The default Settings() uses QSettings(organization, application), which Qt
    pins to the native store (the real preferences on macOS) no matter what
    setDefaultFormat says. Injecting a file-backed QSettings is the only way
    to keep tests off the developer's own configuration.
    """
    return Settings(QSettings(str(settings_file), QSettings.Format.IniFormat))


@pytest.fixture
def make_downloader(qapp):
    """Build ModelDownloaders that stay alive until their replies are gone.

    A finished reply is handed to deleteLater(). If the downloader, and with
    it the QNetworkAccessManager, is garbage-collected before that deferred
    delete runs, Qt crashes. The app never gets there because its downloader
    lives as long as the main window, but a test's local variable does not.
    """
    created = []

    def _make(models_dir) -> ModelDownloader:
        downloader = ModelDownloader(str(models_dir))
        created.append(downloader)
        return downloader

    yield _make
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def spawned(monkeypatch) -> list[list[str]]:
    """Record the commands the app would launch (the native file manager)."""
    commands: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, *a, **kw: commands.append(list(args)))
    return commands


@pytest.fixture
def models_dir(tmp_path):
    """A models folder holding one model file and the manifest that names it."""
    path = tmp_path / "models"
    path.mkdir()
    shutil.copy(DETECT_MODEL, path / "tiny-detect.onnx")
    manifest = [{
        "name": "Tiny Detect",
        "url": "https://example.invalid/tiny-detect.onnx",
        "size_mb": 1,
        "release_date": "2026-01-01",
    }]
    (path / "models.json").write_text(json.dumps(manifest))
    return path


@pytest.fixture
def detector_factory() -> FakeDetectorFactory:
    return FakeDetectorFactory(class_names={1: "Fish", 2: "Crab"})


@pytest.fixture
def make_window(qtbot, spawned, settings, models_dir, detector_factory):
    """Build a real DetectoristApp on test doubles.

    The worker and its QThread are real. qtbot closes each window on
    teardown, and closeEvent joins the thread, so none outlives its test.
    """
    # Imported here so the pure tests do not need the generated ui_*.py files
    from detectorist.detectorist_app import DetectoristApp

    windows = []

    def _make(*, wait_for_model=True, **overrides):
        kwargs = {"settings": settings, "models_dir": str(models_dir), "detector_factory": detector_factory}
        window = DetectoristApp(**(kwargs | overrides))
        qtbot.addWidget(window)
        windows.append(window)
        if wait_for_model:
            # The class filter holds only "All classes" until a model reports its classes
            qtbot.waitUntil(lambda: window.ui.class_filter_combo_box.count() > 1)
        return window

    yield _make
    # A simulated key click with a modifier leaves that modifier set on the
    # application. The next test's setCurrentIndex() would then extend the
    # selection as if Ctrl were still held. An unmodified key event clears it.
    for window in windows:
        QTest.keyRelease(window, Qt.Key.Key_Shift)


@pytest.fixture
def window(make_window):
    return make_window()


@pytest.fixture
def stalled_server():
    """A local HTTP server that sends the start of a file and then stalls.

    Cancelling needs a download that is still in flight. A file:// reply
    completes at once and does not report an abort the way an HTTP reply does,
    so the cancel tests talk to a real socket on localhost. requested is set
    once the server has started answering, and url is the server's base URL.
    """
    requested = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "1000000")
            self.end_headers()
            self.wfile.write(b"x" * 1000)
            self.wfile.flush()
            requested.set()
            release.wait(10)

        def log_message(self, *args):
            pass

    class Server(socketserver.ThreadingTCPServer):
        # Not http.server.HTTPServer: on bind it resolves its own host name,
        # a reverse DNS query that took 35 s on the GitHub macOS runner. The
        # handler does not need the name.
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    # The default poll interval of 0.5 s is how long shutdown() would block
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    server.requested = requested
    server.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield server
    release.set()
    server.shutdown()
    server.server_close()
