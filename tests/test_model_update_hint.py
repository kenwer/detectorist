"""Tests for the status bar link that points to Manage Models when a model has a newer version.

A real ModelDownloader reads its cached manifest from a models folder in
tmp_path, and downloads come from another folder through file:// URLs.
"""

import json

import pytest
from PySide6.QtCore import QUrl

from detectorist.model_downloader import ModelDownloader
from detectorist.model_update_hint import ModelUpdateHint


def file_url(path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


@pytest.fixture
def remote(tmp_path):
    """The folder playing the download server, holding the new versions."""
    remote = tmp_path / "remote"
    remote.mkdir()
    for filename in ("fish-v2.onnx", "bee-v2.onnx"):
        (remote / filename).write_bytes(f"model {filename}".encode())
    return remote


@pytest.fixture
def make_hint(qtbot, make_downloader, tmp_path, remote):
    """A hint on a models folder holding the given files. Returns it and its downloader."""
    def _make(*installed: str) -> tuple[ModelUpdateHint, ModelDownloader]:
        models = tmp_path / "models"
        models.mkdir()
        (models / "models.json").write_text(json.dumps([
            {"name": "Fish", "url": file_url(remote / "fish-v2.onnx"), "supersedes": ["fish-v1.onnx"]},
            {"name": "Bee", "url": file_url(remote / "bee-v2.onnx"), "supersedes": ["bee-v1.onnx"]},
        ]))
        for filename in installed:
            (models / filename).write_bytes(b"installed")
        downloader = make_downloader(models)
        hint = ModelUpdateHint(downloader)
        qtbot.addWidget(hint)
        return hint, downloader

    return _make


def shown(hint: ModelUpdateHint) -> bool:
    # isVisible() also needs the unplaced hint's window to be shown, the flag is the hint's own say
    return not hint.isHidden()


def test_no_link_without_outdated_models(make_hint):
    hint, _ = make_hint("fish-v2.onnx")

    assert not shown(hint)


@pytest.mark.parametrize(("installed", "text"), [
    (("fish-v1.onnx",), "Model update available"),
    (("fish-v1.onnx", "bee-v1.onnx"), "2 model updates available"),
])
def test_link_names_the_number_of_updates(make_hint, installed, text):
    hint, _ = make_hint(*installed)

    assert shown(hint)
    assert text in hint.text()


def test_suppressed_link_waits_until_released(make_hint):
    hint, _ = make_hint("fish-v1.onnx")

    hint.set_suppressed(True)
    assert not shown(hint)

    hint.set_suppressed(False)
    assert shown(hint)


def test_link_goes_once_the_update_is_downloaded(qtbot, make_hint):
    hint, downloader = make_hint("fish-v1.onnx")

    downloader.download(downloader.outdated_models())
    qtbot.waitUntil(lambda: not downloader.is_downloading)

    assert not shown(hint)
