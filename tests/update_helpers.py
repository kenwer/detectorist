"""Shared doubles for the in-app update tests."""

import socketserver
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from PySide6.QtCore import QObject, QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from detectorist.update.feed import Update
from detectorist.update.install import LinuxAppInstall

# A release the update tests offer over version 0.8.0
UPDATE = Update("0.9.0", "notes", "https://example.org/r", "a.AppImage", "https://example.org/a", 10, "0" * 64)


def linux_install(tmp_path: Path) -> LinuxAppInstall:
    return LinuxAppInstall(tmp_path / "Detectorist.AppImage", tmp_path / "stage")


def no_progress(_done: int, _total: int) -> None:
    pass


def never() -> bool:
    return False


def stop_worker_threads(owner: QObject) -> None:
    """Stop the QThreads under owner, so none is destroyed while it runs."""
    for thread in owner.findChildren(QThread):
        thread.requestInterruption()
        thread.quit()
        thread.wait(5000)


class RecordingWindow(QMainWindow):
    """Records an accepted close. A closing window is already hidden, so visibility cannot tell."""

    closed = False
    refuse_close = False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802  Qt API
        if self.refuse_close:
            event.ignore()
            return
        super().closeEvent(event)
        self.closed = event.isAccepted()


@dataclass
class Route:
    body: bytes
    status: int = 200
    content_type: str = "application/octet-stream"


@dataclass
class FakeServer:
    """A local HTTP server whose answers each test configures.

    honor_range: answer "Range: bytes=N-" with 206, else ignore it (200).
    cut_after: on the next request only, send this many body bytes, then drop the connection.
    """

    port: int = 0
    routes: dict[str, Route] = field(default_factory=dict)
    honor_range: bool = True
    cut_after: int | None = None
    requests: list[dict[str, str]] = field(default_factory=list)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"


def fake_server_handler(state: FakeServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802  http.server API
            state.requests.append({"path": self.path, **dict(self.headers)})
            route = state.routes.get(self.path)
            if route is None:
                self.send_error(404)
                return
            body, status = route.body, route.status
            start = 0
            range_header = self.headers.get("Range")
            if status == 200 and range_header and state.honor_range:
                start = int(range_header.removeprefix("bytes=").rstrip("-"))
                status = 206
            chunk = body[start:]
            self.send_response(status)
            self.send_header("Content-Type", route.content_type)
            self.send_header("Content-Length", str(len(chunk)))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            self.end_headers()
            if state.cut_after is not None:
                cut, state.cut_after = state.cut_after, None
                self.wfile.write(chunk[:cut])
                self.wfile.flush()
                self.close_connection = True
                return
            self.wfile.write(chunk)

    return Handler


class QuietServer(socketserver.ThreadingTCPServer):
    # Not http.server.HTTPServer, which resolves its own host name on bind (see stalled_server in conftest.py)
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        pass  # a client hanging up mid-body is what the cancel tests do
