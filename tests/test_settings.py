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


def stored_keys(settings_file) -> set[str]:
    return set(QSettings(str(settings_file), QSettings.Format.IniFormat).allKeys())


def test_unset_values_read_as_none(settings):
    assert settings.newest_version is None
    assert settings.detection_model is None
    assert settings.detection_min_confidence_percent is None
    assert settings.classification_model is None
    assert settings.classification_min_confidence_percent is None
    assert settings.image_correct_exposure is None
    assert settings.crop_mode is None
    assert settings.crop_aspect_ratio is None
    assert settings.crop_padding_percent is None
    assert settings.crop_images is None
    assert settings.window_geometry is None
    assert settings.main_splitter_state is None
    assert settings.image_splitter_state is None


def test_values_keep_their_type_across_a_reopen(settings, settings_file):
    settings.detection_model = "fish.onnx.gz"
    settings.detection_min_confidence_percent = 60
    settings.classification_model = "fish-species.onnx.gz"
    settings.classification_min_confidence_percent = 35
    settings.image_correct_exposure = False
    settings.crop_mode = "most_centered"
    settings.crop_aspect_ratio = "3:2"
    settings.crop_padding_percent = 0
    settings.crop_images = False
    settings.window_geometry = QByteArray(b"\x01\x02")

    reopened = reopen(settings_file)

    assert reopened.detection_model == "fish.onnx.gz"
    assert reopened.detection_min_confidence_percent == 60
    assert reopened.classification_model == "fish-species.onnx.gz"
    assert reopened.classification_min_confidence_percent == 35
    assert reopened.image_correct_exposure is False
    assert reopened.crop_mode == "most_centered"
    assert reopened.crop_aspect_ratio == "3:2"
    assert reopened.crop_padding_percent == 0
    assert reopened.crop_images is False
    assert reopened.window_geometry == QByteArray(b"\x01\x02")


def test_settings_are_stored_under_their_group_and_key(settings, settings_file):
    settings.detection_min_confidence_percent = 60
    settings.classification_model = "fish-species.onnx.gz"
    settings.image_correct_exposure = True
    settings.crop_aspect_ratio = "1:1"
    settings.crop_images = True
    settings.add_recent_folder("/photos/a")
    settings.main_splitter_state = QByteArray(b"\x01")
    settings.save_current_version()

    assert stored_keys(settings_file) == {
        "model/detection_min_confidence_percent", "model/classification_model", "image/correct_exposure", "crop/aspect_ratio",
        "crop/images", "recent/directories", "ui/main_splitter_state", "app/newest_version"}


@pytest.mark.parametrize(("name", "value"), [("classification_model", "something"),
                                           ("detection_model", "something"), ("crop_padding_percent", 10)])
def test_none_is_stored_and_read_back_as_none(settings, settings_file, name, value):
    setattr(settings, name, value)
    setattr(settings, name, None)

    assert getattr(reopen(settings_file), name) is None


def test_recent_folders_of_earlier_versions_are_kept(settings_file):
    old = QSettings(str(settings_file), QSettings.Format.IniFormat)
    old.setValue("recent/directories", ["/photos/a", "/photos/b"])
    old.sync()

    assert reopen(settings_file).recent_folders == ["/photos/a", "/photos/b"]


def test_save_current_version(settings):
    settings.save_current_version()
    assert settings.newest_version == __version__


def store_saved_by(settings_file, version: str | None) -> None:
    """A store as the build of the given version left it, with a key this build does not know."""
    store = QSettings(str(settings_file), QSettings.Format.IniFormat)
    if version is not None:
        store.setValue("app/newest_version", version)
    store.setValue("model/detection_model", "fish.onnx.gz")
    store.setValue("model/unknown_key", 1)
    store.setValue("other/key", 1)
    store.sync()


@pytest.mark.parametrize("saved_by", [None, "0.11.0", "0.12.0", "0.12.0.dev5", "not a version"])
def test_unknown_keys_of_an_older_build_are_removed(settings_file, monkeypatch, saved_by):
    monkeypatch.setattr("detectorist.settings.__version__", "0.12.0")
    store_saved_by(settings_file, saved_by)

    reopen(settings_file).save_current_version()

    assert stored_keys(settings_file) == {"model/detection_model", "other/key", "app/newest_version"}
    assert reopen(settings_file).newest_version == "0.12.0"


@pytest.mark.parametrize("saved_by", ["0.12.1.dev3", "0.13.0"])
def test_keys_of_a_newer_build_are_kept_across_restarts(settings_file, monkeypatch, saved_by):
    monkeypatch.setattr("detectorist.settings.__version__", "0.12.0")
    store_saved_by(settings_file, saved_by)

    reopen(settings_file).save_current_version()
    reopen(settings_file)

    assert "model/unknown_key" in stored_keys(settings_file)
    assert reopen(settings_file).newest_version == saved_by


def test_a_build_without_a_version_removes_and_records_nothing(settings_file, monkeypatch):
    monkeypatch.setattr("detectorist.settings.__version__", "unknown")
    store_saved_by(settings_file, "0.12.0")

    reopen(settings_file).save_current_version()

    assert "model/unknown_key" in stored_keys(settings_file)
    assert reopen(settings_file).newest_version == "0.12.0"


def test_last_folder_defaults_to_home(settings):
    assert settings.recent_folders == []
    assert settings.last_folder == QDir.homePath()


def test_single_recent_folder_reads_back_as_a_list(settings, settings_file):
    # QSettings collapses a one-element list to a plain string in INI files
    settings.add_recent_folder("/photos/a")

    assert reopen(settings_file).recent_folders == ["/photos/a"]


def test_recent_folders_are_most_recent_first_without_duplicates(settings):
    settings.add_recent_folder("/photos/a")
    settings.add_recent_folder("/photos/b")
    settings.add_recent_folder("/photos/a")

    assert settings.recent_folders == ["/photos/a", "/photos/b"]
    assert settings.last_folder == "/photos/a"


def test_recent_folders_are_capped(settings):
    for i in range(Settings.MAX_RECENT_FOLDERS + 3):
        settings.add_recent_folder(f"/photos/{i}")

    recent = settings.recent_folders
    assert len(recent) == Settings.MAX_RECENT_FOLDERS
    assert recent[0] == f"/photos/{Settings.MAX_RECENT_FOLDERS + 2}"


def test_clear_recent_folders(settings):
    settings.add_recent_folder("/photos/a")
    settings.clear_recent_folders()
    assert settings.recent_folders == []


def test_reset_clears_the_portable_settings_but_keeps_recent_and_layout(settings):
    settings.detection_model = "fish.onnx"
    settings.classification_min_confidence_percent = 35
    settings.image_correct_exposure = False
    settings.crop_padding_percent = 10
    settings.crop_images = False
    settings.add_recent_folder("/photos/a")
    settings.window_geometry = QByteArray(b"\x01")

    settings.reset_to_defaults()

    assert settings.detection_model is None
    assert settings.classification_min_confidence_percent is None
    assert settings.image_correct_exposure is None
    assert settings.crop_padding_percent is None
    assert settings.crop_images is None
    assert settings.recent_folders == ["/photos/a"]
    assert settings.window_geometry == QByteArray(b"\x01")


def test_export_writes_every_portable_setting_with_its_json_type(settings, tmp_path):
    settings.detection_model = "fish.onnx.gz"
    settings.detection_min_confidence_percent = 52
    settings.classification_model = None
    settings.classification_min_confidence_percent = 61
    settings.image_correct_exposure = True
    settings.crop_mode = "best_classification"
    settings.crop_aspect_ratio = "detection_frame"
    settings.crop_padding_percent = 15
    settings.crop_images = True
    settings.add_recent_folder("/photos/a")
    export_path = tmp_path / "exported.json"

    settings.export_to_file(export_path)

    assert json.loads(export_path.read_text()) == {
        "app_version": __version__,
        "settings": {
            "model": {"detection_model": "fish.onnx.gz", "detection_min_confidence_percent": 52,
                      "classification_model": None, "classification_min_confidence_percent": 61},
            "image": {"correct_exposure": True},
            "crop": {"mode": "best_classification", "aspect_ratio": "detection_frame", "padding_percent": 15,
                     "images": True},
        },
    }


def test_export_writes_unset_settings_as_null(settings, tmp_path):
    export_path = tmp_path / "exported.json"

    settings.export_to_file(export_path)

    assert json.loads(export_path.read_text())["settings"]["crop"] == {
        "mode": None, "aspect_ratio": None, "padding_percent": None, "images": None}


def test_export_then_import_restores_typed_values(settings, tmp_path):
    settings.detection_min_confidence_percent = 60
    settings.crop_mode = "most_centered"
    settings.image_correct_exposure = False
    settings.classification_model = "fish-species.onnx.gz"
    export_path = tmp_path / "exported.json"
    settings.export_to_file(export_path)

    other = reopen(tmp_path / "other.ini")
    other.import_from_file(export_path)

    assert other.detection_min_confidence_percent == 60
    assert other.crop_mode == "most_centered"
    assert other.image_correct_exposure is False
    assert other.classification_model == "fish-species.onnx.gz"


def test_importing_null_unsets_a_setting(settings, tmp_path):
    settings.classification_model = "fish-species.onnx.gz"
    import_path = tmp_path / "import.json"
    import_path.write_text(json.dumps({"settings": {"model": {"classification_model": None}}}))

    settings.import_from_file(import_path)

    assert settings.classification_model is None


def test_import_ignores_unknown_groups_and_keys(settings, settings_file, tmp_path):
    import_path = tmp_path / "import.json"
    import_path.write_text(json.dumps({
        "settings": {
            "model": {"detection_min_confidence_percent": 33, "colour": "red"},
            "recent": {"folders": ["/somewhere/else"]},
            "ui": {"window_geometry": "abc"},
        }
    }))

    settings.import_from_file(import_path)

    assert settings.detection_min_confidence_percent == 33
    assert stored_keys(settings_file) == {"model/detection_min_confidence_percent"}


def test_import_of_a_file_without_settings_changes_nothing(settings, tmp_path):
    settings.detection_min_confidence_percent = 60
    import_path = tmp_path / "import.json"
    import_path.write_text('{"settings": {}}')

    settings.import_from_file(import_path)

    assert settings.detection_min_confidence_percent == 60


@pytest.mark.parametrize("content", [
    "[]",
    "{}",
    '{"settings": []}',
    '{"settings": {"model": 5}}',
    '{"groups": {"model": {"confidence": 33}}}',
    '{"settings": {"model": {"detection_min_confidence_percent": "33"}}}',
    '{"settings": {"image": {"correct_exposure": 1}}}',
    '{"settings": {"crop": {"padding_percent": true}}}',
])
def test_import_of_json_that_is_not_a_settings_file_is_rejected(settings, tmp_path, content):
    settings.detection_min_confidence_percent = 60
    settings.crop_padding_percent = 10
    import_path = tmp_path / "import.json"
    import_path.write_text(content)

    with pytest.raises(ValueError, match="not a settings file"):
        settings.import_from_file(import_path)

    assert settings.detection_min_confidence_percent == 60
    assert settings.crop_padding_percent == 10
