"""Tests for ModelDownloader.

QNetworkAccessManager serves file:// URLs, so a folder in tmp_path stands in
for the download server and nothing touches the network. The downloader is
driven through its public methods and observed through its signals and the
files it leaves behind.
"""

import json
import os

import pytest
from PySide6.QtCore import QUrl

from detectorist import model_downloader
from detectorist.model_downloader import model_filename_from_url


def file_url(path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


@pytest.fixture
def remote(tmp_path):
    """The folder playing the download server, holding two model files."""
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "a.onnx").write_bytes(b"model-a")
    (remote / "b.onnx").write_bytes(b"model-b")
    return remote


@pytest.fixture
def target(tmp_path):
    """The local models folder downloads are written to."""
    target = tmp_path / "target"
    target.mkdir()
    return target


def entry(remote, filename, **extra) -> dict:
    return {"name": filename.split(".")[0].upper(), "url": file_url(remote / filename), **extra}


def record_events(downloader) -> list:
    events = []
    downloader.download_started.connect(lambda filename: events.append(("started", filename)))
    downloader.download_finished.connect(lambda filename: events.append(("finished", filename)))
    downloader.download_error.connect(lambda message: events.append(("error", message)))
    return events


def test_model_filename_from_url():
    assert model_filename_from_url("https://example.org/models/fish.onnx.gz") == "fish.onnx.gz"


def test_cached_manifest_names_current_and_superseded_files(make_downloader, target):
    (target / "models.json").write_text(json.dumps([
        {"name": "Fish", "url": "https://example.org/fish-v2.onnx", "supersedes": ["fish-v1.onnx"]},
        {"name": "Bee", "url": "https://example.org/bee.onnx"},
    ]))

    downloader = make_downloader(target)

    assert downloader.filename_to_name == {"fish-v2.onnx": "Fish", "fish-v1.onnx": "Fish", "bee.onnx": "Bee"}


def test_superseded_name_never_replaces_a_current_file_name(make_downloader, target):
    (target / "models.json").write_text(json.dumps([
        {"name": "Kept", "url": "https://example.org/kept.onnx"},
        {"name": "New", "url": "https://example.org/new.onnx", "supersedes": ["kept.onnx"]},
    ]))

    assert make_downloader(target).filename_to_name["kept.onnx"] == "Kept"


def test_missing_or_corrupt_cached_manifest_gives_no_names(make_downloader, target):
    assert make_downloader(target).filename_to_name == {}

    (target / "models.json").write_text("not json")
    assert make_downloader(target).filename_to_name == {}


def test_fetch_manifest_emits_the_parsed_list(qtbot, make_downloader, monkeypatch, remote, target):
    manifest = [entry(remote, "a.onnx")]
    (remote / "models.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(model_downloader, "MANIFEST_URL", file_url(remote / "models.json"))
    downloader = make_downloader(target)

    with qtbot.waitSignal(downloader.manifest_loaded) as loaded:
        downloader.fetch_manifest()

    assert loaded.args == [manifest]
    assert downloader.filename_to_name == {"a.onnx": "A"}


def test_fetch_manifest_reports_a_missing_manifest(qtbot, make_downloader, target):
    # The autouse _no_network fixture points MANIFEST_URL at a missing file
    downloader = make_downloader(target)

    with qtbot.waitSignal(downloader.download_error) as failed:
        downloader.fetch_manifest()

    assert failed.args[0].startswith("Failed to fetch manifest")


def test_fetch_manifest_reports_invalid_json(qtbot, make_downloader, monkeypatch, remote, target):
    (remote / "models.json").write_text("not json")
    monkeypatch.setattr(model_downloader, "MANIFEST_URL", file_url(remote / "models.json"))
    downloader = make_downloader(target)

    with qtbot.waitSignal(downloader.download_error) as failed:
        downloader.fetch_manifest()

    assert failed.args[0].startswith("Invalid manifest")


def test_queued_models_download_in_order(qtbot, make_downloader, remote, target):
    downloader = make_downloader(target)
    events = record_events(downloader)

    with qtbot.waitSignal(downloader.all_downloads_finished):
        downloader.download([entry(remote, "a.onnx"), entry(remote, "b.onnx")])

    assert events == [("started", "a.onnx"), ("finished", "a.onnx"), ("started", "b.onnx"), ("finished", "b.onnx")]
    assert (target / "a.onnx").read_bytes() == b"model-a"
    assert (target / "b.onnx").read_bytes() == b"model-b"
    assert sorted(os.listdir(target)) == ["a.onnx", "b.onnx"]  # no .part files left
    assert downloader.is_downloading is False


def test_state_while_a_download_is_active(qtbot, make_downloader, remote, target):
    downloader = make_downloader(target)

    with qtbot.waitSignal(downloader.all_downloads_finished):
        downloader.download([entry(remote, "a.onnx"), entry(remote, "b.onnx")])
        # Nothing has been delivered yet: the replies arrive through the event loop
        assert downloader.is_downloading is True
        assert downloader.current_filename == "a.onnx"
        assert downloader.queued_filenames == ["b.onnx"]


def test_download_replaces_an_existing_file(qtbot, make_downloader, remote, target):
    (target / "a.onnx").write_bytes(b"stale")
    downloader = make_downloader(target)

    with qtbot.waitSignal(downloader.all_downloads_finished):
        downloader.download([entry(remote, "a.onnx")])

    assert (target / "a.onnx").read_bytes() == b"model-a"


def test_finished_download_deletes_the_files_it_supersedes(qtbot, make_downloader, remote, target):
    model = entry(remote, "a.onnx", supersedes=["a-old.onnx"])
    (target / "models.json").write_text(json.dumps([model]))
    (target / "a-old.onnx").write_bytes(b"old")
    downloader = make_downloader(target)

    with qtbot.waitSignal(downloader.all_downloads_finished):
        downloader.download([model])

    assert not (target / "a-old.onnx").exists()
    assert (target / "a.onnx").exists()


def test_failed_download_reports_the_error_and_drops_the_queue(qtbot, make_downloader, remote, target):
    downloader = make_downloader(target)
    events = record_events(downloader)

    with qtbot.waitSignal(downloader.download_error) as failed:
        downloader.download([entry(remote, "missing.onnx"), entry(remote, "b.onnx")])

    assert failed.args[0].startswith("Download failed")
    assert ("started", "b.onnx") not in events
    assert os.listdir(target) == []
    assert downloader.is_downloading is False


def test_cancel_stops_the_download_and_drops_the_queue(qtbot, make_downloader, stalled_server, target):
    downloader = make_downloader(target)
    events = record_events(downloader)

    downloader.download([{"url": f"{stalled_server.url}/a.onnx"}, {"url": f"{stalled_server.url}/b.onnx"}])
    qtbot.waitUntil(stalled_server.requested.is_set)
    downloader.cancel()

    assert downloader.is_downloading is False
    assert downloader.queued_filenames == []
    assert os.listdir(target) == []  # the partial file is removed
    # A cancel the user asked for is not a failed download
    assert events == [("started", "a.onnx")]
