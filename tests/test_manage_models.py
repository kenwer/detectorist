"""Tests for the Manage Models dialog.

The dialog is built on a real ModelDownloader whose manifest and model files
come from a folder in tmp_path through file:// URLs. Rows are found by model
filename. Their state is read from the dialog's row objects, which is the
one place these tests reach into dialog internals.
"""

import json

import pytest
from PySide6.QtCore import QUrl

from detectorist import model_downloader
from detectorist.manage_models import ManageModelsDialog
from detectorist.model_downloader import model_filename_from_url


def file_url(path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """The folder playing the download server: three models and their manifest."""
    remote = tmp_path / "remote"
    remote.mkdir()
    for filename in ("a.onnx", "b.onnx", "c-v2.onnx"):
        (remote / filename).write_bytes(f"model {filename}".encode())
    manifest = [
        {"name": "Model A", "url": file_url(remote / "a.onnx"), "size_mb": 1, "release_date": "2026-01-01"},
        {"name": "Model B", "url": file_url(remote / "b.onnx"), "size_mb": 1, "release_date": "2026-01-02"},
        {"name": "Model C", "url": file_url(remote / "c-v2.onnx"), "size_mb": 1, "release_date": "2026-01-03",
         "supersedes": ["c-v1.onnx"]},
    ]
    (remote / "models.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(model_downloader, "MANIFEST_URL", file_url(remote / "models.json"))
    return remote


@pytest.fixture
def open_dialog(qtbot, make_downloader, tmp_path, remote):
    """Open the dialog on a models folder holding the given installed files."""

    def _open(installed=()):
        models = tmp_path / "models"
        models.mkdir()
        for filename in installed:
            (models / filename).write_bytes(b"installed")
        dialog = ManageModelsDialog(make_downloader(models), str(models))
        qtbot.addWidget(dialog)
        qtbot.waitUntil(lambda: len(dialog._rows) > 0)
        return dialog, models

    return _open


def states(dialog) -> dict[str, str]:
    return {model_filename_from_url(row.model["url"]): row.state for row in dialog._rows}


def button(dialog, filename):
    (row,) = [row for row in dialog._rows if model_filename_from_url(row.model["url"]) == filename]
    return row.action_button


def test_rows_reflect_what_is_on_disk(open_dialog):
    dialog, _ = open_dialog(installed=("a.onnx", "c-v1.onnx", "mine.onnx"))

    # c-v1.onnx gets no row of its own: the outdated Model C row stands for it
    assert states(dialog) == {
        "a.onnx": "downloaded",
        "b.onnx": "available",
        "c-v2.onnx": "outdated",
        "mine.onnx": "local_only",
    }
    assert button(dialog, "a.onnx").text() == "Remove"
    assert button(dialog, "b.onnx").text() == "Download"
    assert button(dialog, "c-v2.onnx").text() == "Update"
    assert button(dialog, "mine.onnx").text() == "Remove"


def test_download_button_fetches_the_model(qtbot, open_dialog):
    dialog, models = open_dialog()

    button(dialog, "b.onnx").click()
    qtbot.waitUntil(lambda: states(dialog)["b.onnx"] == "downloaded")

    assert (models / "b.onnx").read_bytes() == b"model b.onnx"
    assert button(dialog, "b.onnx").text() == "Remove"


def test_update_replaces_the_superseded_file(qtbot, open_dialog):
    dialog, models = open_dialog(installed=("c-v1.onnx",))

    button(dialog, "c-v2.onnx").click()
    qtbot.waitUntil(lambda: states(dialog)["c-v2.onnx"] == "downloaded")

    assert (models / "c-v2.onnx").exists()
    assert not (models / "c-v1.onnx").exists()


def test_remove_deletes_the_file_and_announces_the_change(qtbot, open_dialog):
    dialog, models = open_dialog(installed=("a.onnx",))

    with qtbot.waitSignal(dialog.models_changed):
        button(dialog, "a.onnx").click()

    assert not (models / "a.onnx").exists()
    assert states(dialog)["a.onnx"] == "available"


def test_removing_a_local_only_model_removes_its_row(qtbot, open_dialog):
    dialog, models = open_dialog(installed=("mine.onnx",))

    with qtbot.waitSignal(dialog.models_changed):
        button(dialog, "mine.onnx").click()

    assert not (models / "mine.onnx").exists()
    assert "mine.onnx" not in states(dialog)


def test_download_all_fetches_every_missing_model(qtbot, open_dialog):
    dialog, models = open_dialog(installed=("a.onnx",))
    assert dialog.ui.download_button.isEnabled()

    dialog.ui.download_button.click()
    qtbot.waitUntil(lambda: set(states(dialog).values()) == {"downloaded"})

    assert sorted(path.name for path in models.iterdir()) == ["a.onnx", "b.onnx", "c-v2.onnx"]
    assert not dialog.ui.download_button.isEnabled()


def test_download_all_is_disabled_when_everything_is_installed(open_dialog):
    dialog, _ = open_dialog(installed=("a.onnx", "b.onnx", "c-v2.onnx"))

    assert not dialog.ui.download_button.isEnabled()


def test_failed_download_marks_the_row_and_shows_the_error(qtbot, open_dialog, remote):
    (remote / "b.onnx").unlink()
    dialog, _ = open_dialog()

    button(dialog, "b.onnx").click()
    qtbot.waitUntil(lambda: states(dialog)["b.onnx"] == "error")

    assert button(dialog, "b.onnx").text() == "Retry"
    assert dialog.ui.status_label.text().startswith("Error: Download failed")


def test_manifest_fetch_failure_is_shown(qtbot, make_downloader, tmp_path, remote):
    (remote / "models.json").unlink()
    models = tmp_path / "models"
    models.mkdir()

    dialog = ManageModelsDialog(make_downloader(models), str(models))
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: dialog.ui.status_label.text().startswith("Error: Failed to fetch manifest"))


def test_cancelling_a_download_makes_the_model_available_again(qtbot, open_dialog, remote, stalled_server):
    manifest = [{"name": "Slow", "url": f"{stalled_server.url}/slow.onnx", "size_mb": 1, "release_date": "2026-01-01"}]
    (remote / "models.json").write_text(json.dumps(manifest))
    dialog, models = open_dialog()

    button(dialog, "slow.onnx").click()
    qtbot.waitUntil(stalled_server.requested.is_set)
    assert button(dialog, "slow.onnx").text() == "Cancel"
    button(dialog, "slow.onnx").click()

    assert states(dialog) == {"slow.onnx": "available"}
    assert button(dialog, "slow.onnx").text() == "Download"
    assert dialog.ui.status_label.text() == "Download cancelled."
    assert list(models.iterdir()) == []
