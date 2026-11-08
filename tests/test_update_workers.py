"""The update workers map the feed and install functions to signals.

Runs worker.run() directly, no QThread, like test_project_load_worker.py.
"""

from pathlib import Path

import pytest

from detectorist.update import feed
from detectorist.update.download import DownloadCancelled
from detectorist.update.feed import UpdateError
from detectorist.update.install import AppInstall, LinuxAppInstall
from detectorist.update.workers import UpdateCheckWorker, UpdateDownloadWorker
from tests.update_helpers import UPDATE, linux_install


def _offer(monkeypatch: pytest.MonkeyPatch, update=UPDATE) -> None:
    monkeypatch.setattr(feed, "fetch_latest_release", lambda url: {"url": url})
    monkeypatch.setattr(feed, "find_update", lambda release, version, asset: update)


def _check(install: AppInstall | None, reuse_staged: bool = True) -> tuple[list, list[str]]:
    """Run a check and return what finished and failed emitted."""
    worker = UpdateCheckWorker("https://feed", "0.8.0", "a.AppImage", install, reuse_staged)
    finished: list = []
    failed: list[str] = []
    worker.finished.connect(lambda update, staged: finished.append((update, staged)))
    worker.failed.connect(failed.append)
    worker.run()
    return finished, failed


def _download(install: AppInstall) -> UpdateDownloadWorker:
    return UpdateDownloadWorker(install, UPDATE)


def test_check_worker_emits_update(monkeypatch: pytest.MonkeyPatch) -> None:
    _offer(monkeypatch)
    assert _check(None) == ([(UPDATE, None)], [])


def test_check_worker_looks_for_a_staged_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    staged = tmp_path / "stage" / "0.9.0" / "a.AppImage"
    _offer(monkeypatch)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda target, update: staged)
    assert _check(linux_install(tmp_path)) == ([(UPDATE, staged)], [])


def test_a_blocked_install_skips_the_staged_lookup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _offer(monkeypatch)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", lambda *_a: pytest.fail("looked for a staged update"))
    assert _check(linux_install(tmp_path), reuse_staged=False) == ([(UPDATE, None)], [])


def test_a_broken_staged_payload_still_reports_the_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def broken(target, update):
        raise UpdateError("Could not unpack the downloaded update")

    _offer(monkeypatch)
    monkeypatch.setattr(LinuxAppInstall, "staged_payload", broken)
    assert _check(linux_install(tmp_path)) == ([(UPDATE, None)], [])


def test_check_worker_emits_failed_on_update_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(url: str) -> dict:
        raise UpdateError("offline")

    monkeypatch.setattr(feed, "fetch_latest_release", offline)
    assert _check(None) == ([], ["offline"])


def test_check_worker_reports_unexpected_errors_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(release, version, asset):
        raise RuntimeError("bug in the parser")

    monkeypatch.setattr(feed, "fetch_latest_release", lambda url: {})
    monkeypatch.setattr(feed, "find_update", broken)
    assert _check(None) == ([], ["bug in the parser"])


def test_check_worker_cleans_up_even_when_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The applied version's staging copy goes, though no feed answers."""
    (tmp_path / "stage" / "0.8.0").mkdir(parents=True)

    def offline(url: str) -> dict:
        raise UpdateError("offline")

    monkeypatch.setattr(feed, "fetch_latest_release", offline)
    _check(linux_install(tmp_path))
    assert not (tmp_path / "stage" / "0.8.0").exists()


def test_download_worker_reports_progress_and_the_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = tmp_path / "stage" / "0.9.0" / "a.AppImage"

    def fake_fetch(target, update, progress, cancelled):
        progress(5, 10)
        progress(10, 10)
        return payload

    monkeypatch.setattr(LinuxAppInstall, "fetch_payload", fake_fetch)
    worker = _download(linux_install(tmp_path))
    progress: list = []
    received: list = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.finished.connect(received.append)
    worker.run()
    assert progress == [(5, 10), (10, 10)]
    assert received == [payload]


def test_download_worker_emits_cancelled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def cancelled_fetch(*_args) -> None:
        raise DownloadCancelled

    monkeypatch.setattr(LinuxAppInstall, "fetch_payload", cancelled_fetch)
    worker = _download(linux_install(tmp_path))
    cancelled: list = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.run()
    assert cancelled == [True]


@pytest.mark.parametrize("error", [UpdateError("checksum mismatch"), RuntimeError("checksum mismatch")])
def test_download_worker_emits_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception) -> None:
    def failing_fetch(*_args) -> None:
        raise error

    monkeypatch.setattr(LinuxAppInstall, "fetch_payload", failing_fetch)
    worker = _download(linux_install(tmp_path))
    failed: list[str] = []
    worker.failed.connect(failed.append)
    worker.run()
    assert failed == ["checksum mismatch"]
