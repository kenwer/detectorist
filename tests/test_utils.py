"""Tests for the path and model-name helpers in utils.

The Windows long-path helpers only do work on Windows, so their real cases
are skipped elsewhere and the pass-through is checked instead.
"""

import os
import sys

import pytest
from PySide6.QtCore import QStandardPaths

from detectorist import utils

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")
not_windows = pytest.mark.skipif(sys.platform == "win32", reason="pass-through on non-Windows platforms")


@pytest.mark.parametrize(("filename", "expected"), [
    ("fish.onnx", "fish"),
    ("fish.onnx.gz", "fish"),
    ("fish-2026-02-15.onnx.gz", "fish-2026-02-15"),
    ("notes.txt", "notes.txt"),
])
def test_strip_model_ext(filename, expected):
    assert utils.strip_model_ext(filename) == expected


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home directory in tmp_path, so the result does not depend on where tmp_path lives."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_contract_user_path_shortens_paths_inside_home(home):
    assert utils.contract_user_path(str(home / "Pictures")) == "~" + os.sep + "Pictures"


def test_contract_user_path_leaves_other_paths_absolute(home, tmp_path):
    outside = str(tmp_path / "elsewhere")
    assert utils.contract_user_path(outside) == outside


def test_get_model_path_prefers_a_populated_local_models_folder(tmp_path, monkeypatch):
    local = tmp_path / "models"
    local.mkdir()
    (local / "models.json").write_text("[]")
    (local / "fish.onnx.gz").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)

    assert utils.get_model_path() == os.path.realpath(local)


def test_get_model_path_falls_back_to_the_app_data_folder(tmp_path, monkeypatch):
    # A models folder without a manifest is not a development checkout
    (tmp_path / "models").mkdir()
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "appdata"

    class FakeStandardPaths:
        StandardLocation = QStandardPaths.StandardLocation

        @staticmethod
        def writableLocation(_location):
            return str(data_dir)

    monkeypatch.setattr(utils, "QStandardPaths", FakeStandardPaths)

    assert utils.get_model_path() == os.path.join(str(data_dir), "models")
    assert (data_dir / "models").is_dir()


@not_windows
def test_long_path_and_resolve_short_path_pass_through(tmp_path):
    path = str(tmp_path / "image.jpg")
    assert utils.long_path(path) == path
    assert utils.resolve_short_path(path) == path


@windows_only
def test_long_path_adds_the_extended_length_prefix():
    assert utils.long_path("C:\\photos\\a.jpg") == "\\\\?\\C:\\photos\\a.jpg"
    assert utils.long_path("C:/photos/a.jpg") == "\\\\?\\C:\\photos\\a.jpg"


@windows_only
def test_long_path_handles_unc_and_already_prefixed_paths():
    assert utils.long_path("\\\\server\\share\\a.jpg") == "\\\\?\\UNC\\server\\share\\a.jpg"
    assert utils.long_path("\\\\?\\C:\\photos\\a.jpg") == "\\\\?\\C:\\photos\\a.jpg"
