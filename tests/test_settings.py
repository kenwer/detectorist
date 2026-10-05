"""Tests for the Settings wrapper around QSettings.

Each test gets a Settings on its own INI file. INI stores every value as a
string, so the typed getters are what turn "60" and "false" back into int
and bool. Several tests reopen the file through a second Settings to prove
the value survived that round trip.
"""

import json

import pytest
from PySide6.QtCore import QByteArray, QDir, QSettings

from detectorist import __version__
from detectorist.settings import Settings


def reopen(settings_file) -> Settings:
    return Settings(QSettings(str(settings_file), QSettings.Format.IniFormat))


def test_unset_values_read_as_none(settings):
    assert settings.version is None
    assert settings.model is None
    assert settings.confidence is None
    assert settings.crop_mode is None
    assert settings.aspect_ratio_index is None
    assert settings.padding is None
    assert settings.auto_correct_exposure_enabled is None
    assert settings.window_geometry is None
    assert settings.splitter_state is None


def test_values_keep_their_type_across_a_reopen(settings, settings_file):
    settings.model = "fish.onnx.gz"
    settings.confidence = 60
    settings.crop_mode = "union"
    settings.aspect_ratio_index = 3
    settings.padding = 0
    settings.auto_correct_exposure_enabled = False
    settings.window_geometry = QByteArray(b"\x01\x02")

    reopened = reopen(settings_file)

    assert reopened.model == "fish.onnx.gz"
    assert reopened.confidence == 60
    assert reopened.crop_mode == "union"
    assert reopened.aspect_ratio_index == 3
    assert reopened.padding == 0
    assert reopened.auto_correct_exposure_enabled is False
    assert reopened.window_geometry == QByteArray(b"\x01\x02")


def test_save_current_version(settings):
    settings.save_current_version()
    assert settings.version == __version__


def test_last_directory_defaults_to_home(settings):
    assert settings.recent_directories == []
    assert settings.last_directory == QDir.homePath()


def test_single_recent_directory_reads_back_as_a_list(settings, settings_file):
    # QSettings collapses a one-element list to a plain string in INI files
    settings.add_recent_directory("/photos/a")

    assert reopen(settings_file).recent_directories == ["/photos/a"]


def test_recent_directories_are_most_recent_first_without_duplicates(settings):
    settings.add_recent_directory("/photos/a")
    settings.add_recent_directory("/photos/b")
    settings.add_recent_directory("/photos/a")

    assert settings.recent_directories == ["/photos/a", "/photos/b"]
    assert settings.last_directory == "/photos/a"


def test_recent_directories_are_capped(settings):
    for i in range(Settings.MAX_RECENT_DIRECTORIES + 3):
        settings.add_recent_directory(f"/photos/{i}")

    recent = settings.recent_directories
    assert len(recent) == Settings.MAX_RECENT_DIRECTORIES
    assert recent[0] == f"/photos/{Settings.MAX_RECENT_DIRECTORIES + 2}"


def test_clear_recent_directories(settings):
    settings.add_recent_directory("/photos/a")
    settings.clear_recent_directories()
    assert settings.recent_directories == []


def test_reset_clears_model_and_crop_but_keeps_recent_and_layout(settings):
    settings.model = "fish.onnx"
    settings.confidence = 60
    settings.padding = 10
    settings.add_recent_directory("/photos/a")
    settings.window_geometry = QByteArray(b"\x01")

    settings.reset_to_defaults()

    assert settings.model is None
    assert settings.confidence is None
    assert settings.padding is None
    assert settings.recent_directories == ["/photos/a"]
    assert settings.window_geometry == QByteArray(b"\x01")


def test_export_writes_only_the_requested_groups(settings, tmp_path):
    settings.confidence = 60
    settings.padding = 10
    settings.add_recent_directory("/photos/a")
    export_path = tmp_path / "exported.json"

    settings.export_to_file(export_path, [Settings.GROUP_MODEL, Settings.GROUP_CROP])

    data = json.loads(export_path.read_text())
    assert data["app_version"] == __version__
    assert set(data["groups"]) == {Settings.GROUP_MODEL, Settings.GROUP_CROP}
    assert int(data["groups"][Settings.GROUP_MODEL]["confidence"]) == 60
    assert int(data["groups"][Settings.GROUP_CROP]["padding"]) == 10


def test_export_then_import_restores_typed_values(settings, tmp_path):
    settings.confidence = 60
    settings.crop_mode = "union"
    settings.auto_correct_exposure_enabled = False
    export_path = tmp_path / "exported.json"
    settings.export_to_file(export_path, [Settings.GROUP_MODEL, Settings.GROUP_CROP])

    other = reopen(tmp_path / "other.ini")
    other.import_from_file(export_path)

    assert other.confidence == 60
    assert other.crop_mode == "union"
    assert other.auto_correct_exposure_enabled is False


def test_import_ignores_groups_that_were_not_requested(settings, tmp_path):
    import_path = tmp_path / "import.json"
    import_path.write_text(json.dumps({
        "groups": {
            "model": {"confidence": 33},
            "recent": {"directories": ["/somewhere/else"]},
        }
    }))

    settings.import_from_file(import_path, [Settings.GROUP_MODEL])

    assert settings.confidence == 33
    assert settings.recent_directories == []


def test_import_of_a_file_without_groups_changes_nothing(settings, tmp_path):
    settings.confidence = 60
    import_path = tmp_path / "import.json"
    import_path.write_text("{}")

    settings.import_from_file(import_path)

    assert settings.confidence == 60


@pytest.mark.parametrize("content", [
    "[]",
    '{"groups": []}',
    '{"groups": {"model": 5}}',
])
def test_import_of_json_that_is_not_a_settings_file_is_rejected(settings, tmp_path, content):
    settings.confidence = 60
    import_path = tmp_path / "import.json"
    import_path.write_text(content)

    with pytest.raises(ValueError, match="not a settings file"):
        settings.import_from_file(import_path)

    assert settings.confidence == 60
