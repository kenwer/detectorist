"""Tests for the main window, DetectoristApp.

A real window is built with a file-backed Settings, a temp models folder and
a fake detector factory. The DetectionWorker and its QThread are real, so
the signal wiring between window and worker is what runs in production.

Tests act through actions and widgets and assert on what the user would see
(labels, bands, list contents, files on disk, recorded toasts). Modal
dialogs are replaced per test with monkeypatch.
"""

import json
import os

import pytest
from PySide6.QtCore import QMimeData, QPointF, QRect, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

from detectorist import __version__
from detectorist.batch_run import detections_csv_name, settings_json_name
from detectorist.detector import Detector
from detectorist.image_object import APPLEDOUBLE_MAGIC
from detectorist.structures import Detection
from detectorist.utils import contract_user_path
from tests.fakes import make_images

IMAGE_SIZE = (200, 100)
FISH = Detection((20, 20, 40, 40), 0.9, "Fish")
FAINT_FISH = Detection((100, 10, 40, 40), 0.4, "Fish")
CRAB = Detection((120, 50, 60, 40), 0.8, "Crab")


@pytest.fixture
def folder(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    return folder


def open_folder(window, folder, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(folder))
    window.ui.open_folder_action.trigger()


def listed(window) -> list[str]:
    return [os.path.basename(path) for path in window.model.imagePaths()]


def object_count(window) -> str:
    """The value of the Objects line in the detection info, "-" while none is shown."""
    return window.ui.detection_info_label.text().splitlines()[0].split(": ")[1]


def select_row(window, row):
    window.ui.image_list_view.setCurrentIndex(window.model.index(row))


def drop(window, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(event)


def test_window_lists_the_model_and_its_classes(window):
    assert window.windowTitle() == f"Detectorist {__version__}"
    assert window.ui.model_select_combo_box.itemText(0) == "Tiny Detect"
    classes = window.ui.class_filter_combo_box
    assert [classes.itemText(i) for i in range(classes.count())] == ["All classes", "Crab", "Fish"]


def test_opening_a_folder_lists_its_images_and_shows_the_first(qtbot, window, folder, monkeypatch, settings):
    make_images(folder, ["b.png", "a.png"], IMAGE_SIZE)
    (folder / "notes.txt").write_text("not an image")

    open_folder(window, folder, monkeypatch)

    assert listed(window) == ["a.png", "b.png"]
    assert window.ui.image_list_view.currentIndex().row() == 0
    qtbot.waitUntil(lambda: window.ui.status_bar.currentMessage() == "a.png")
    assert "200x100" in window.ui.image_info_label.text()
    assert settings.recent_directories == [str(folder)]
    assert window.ui.crop_and_export_all_images_action.isEnabled()
    assert window.ui.crop_and_export_selected_images_action.isEnabled()


def test_opening_image_files_lists_them(window, folder, monkeypatch):
    paths = make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([paths[1]], ""))

    window.ui.open_images_action.trigger()

    assert listed(window) == ["b.png"]


def test_folder_without_images_says_so(window, folder, monkeypatch):
    (folder / "notes.txt").write_text("not an image")

    open_folder(window, folder, monkeypatch)

    assert listed(window) == []
    assert window.ui.image_label.text() == "No supported images found or selected."
    assert not window.ui.crop_and_export_all_images_action.isEnabled()


def test_dropping_a_folder_loads_its_images(window, folder):
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)

    drop(window, [folder])

    assert listed(window) == ["a.png", "b.png"]


def test_dropping_files_skips_sidecars_and_unsupported_files(window, folder):
    (image,) = make_images(folder, ["a.png"], IMAGE_SIZE)
    sidecar = folder / "._a.png"
    sidecar.write_bytes(APPLEDOUBLE_MAGIC + b"\x00" * 20)
    notes = folder / "notes.txt"
    notes.write_text("not an image")

    drop(window, [image, sidecar, notes])

    assert listed(window) == ["a.png"]


def test_selected_image_shows_detections_above_the_confidence(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, FAINT_FISH]
    window.ui.confidence_slider.setValue(50)

    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    assert len(window.ui.image_label.detection_bands) == 1
    assert "0.9000" in window.ui.detection_info_label.text()


def test_lowering_the_confidence_reveals_detections_without_a_new_inference(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, FAINT_FISH]
    window.ui.confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    window.ui.confidence_slider.setValue(30)

    assert object_count(window) == "2"
    assert detector_factory.created[0].detected == ["a.png"]


def test_class_filter_restricts_the_shown_detections(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, CRAB]
    window.ui.confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "2")

    window.ui.class_filter_combo_box.setCurrentText("Crab")

    assert object_count(window) == "1"
    assert [name for _rect, _score, name in window.ui.image_label.orig_detection_rects] == ["Crab"]


def test_selecting_another_image_shows_its_detections(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH]
    window.ui.confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    select_row(window, 1)

    qtbot.waitUntil(lambda: object_count(window) == "0")
    assert window.ui.status_bar.currentMessage() == "b.png"
    assert window.ui.image_label.detection_bands == []


def test_arrow_keys_move_through_the_list(qtbot, window, folder, monkeypatch):
    make_images(folder, ["a.png", "b.png", "c.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)

    qtbot.keyClick(window, Qt.Key.Key_Right)
    assert window.ui.image_list_view.currentIndex().row() == 1

    qtbot.keyClick(window, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert window.ui.image_list_view.currentIndex().row() == 2

    qtbot.keyClick(window, Qt.Key.Key_Right)
    assert window.ui.image_list_view.currentIndex().row() == 2  # stops at the end

    qtbot.keyClick(window, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert window.ui.image_list_view.currentIndex().row() == 0


def test_result_for_another_image_is_ignored(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH]
    window.ui.confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    # What a late answer from the worker looks like after the user moved on
    window.handle_detection_complete(str(folder / "earlier.png"), [FISH, CRAB], 1.0)

    assert object_count(window) == "1"


@pytest.mark.parametrize(("radio_name", "expected"), [
    ("rb_crop_all_detected_objects", [QRect(20, 20, 40, 40), QRect(120, 50, 60, 40)]),
    ("rb_crop_to_top_conf", [QRect(20, 20, 40, 40)]),
    ("rb_crop_union", [QRect(20, 20, 160, 70)]),
    ("rb_crop_centered_obj", [QRect(120, 50, 60, 40)]),
])
def test_crop_bands_follow_the_crop_mode(qtbot, window, folder, monkeypatch, detector_factory, radio_name, expected):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, CRAB]
    window.ui.confidence_slider.setValue(50)
    # No padding and the detection's own aspect ratio make the crop equal the box
    window.ui.padding_slider.setValue(0)
    window.ui.crop_ratio_combo_box.setCurrentText("aspect ratio: same as detection frame")
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "2")

    getattr(window.ui, radio_name).setChecked(True)

    assert window.ui.image_label.last_crop_rects == expected
    assert len(window.ui.image_label.crop_bands) == len(expected)


def test_overlay_action_hides_the_detection_bands(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH]
    window.ui.confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    window.ui.toggle_detection_overlay_action.setChecked(False)

    assert window.ui.image_label.detection_bands[0].isHidden()


def test_unreadable_image_reports_an_error(qtbot, window, folder, monkeypatch, toasts):
    (folder / "broken.png").write_bytes(b"this is not a png")

    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: len(toasts) == 1)

    kind, title, text, _kwargs = toasts[0]
    assert (kind, title) == ("error", "Could not process image")
    assert text.startswith("broken.png: ")
    assert window.ui.image_label.text().startswith("Error: ")


def test_model_that_fails_to_load_is_reported(qtbot, make_window, detector_factory):
    detector_factory.error = OSError("boom")

    window = make_window(wait_for_model=False)

    qtbot.waitUntil(lambda: window.ui.image_label.text() == "Error loading model: boom")


def test_without_models_the_dialog_is_offered_and_model_actions_stay_disabled(qtbot, make_window, tmp_path, folder, monkeypatch):
    from detectorist.detectorist_app import DetectoristApp

    offered = []
    # The real method opens a modal dialog, which would block the test
    monkeypatch.setattr(DetectoristApp, "show_manage_models_dialog", lambda self: offered.append(True))
    empty = tmp_path / "no-models"
    empty.mkdir()
    make_images(folder, ["a.png"], IMAGE_SIZE)

    window = make_window(models_dir=str(empty), wait_for_model=False)
    qtbot.waitUntil(lambda: offered == [True])
    open_folder(window, folder, monkeypatch)

    assert listed(window) == ["a.png"]
    assert window.ui.image_label.text().startswith("No models available")
    assert not window.ui.crop_and_export_all_images_action.isEnabled()
    assert not window.ui.group_images_by_object_class_action.isEnabled()


def test_real_detector_runs_end_to_end(qtbot, make_window, folder, monkeypatch):
    # The models folder holds the tiny ONNX model, which reports three
    # detections with scores of about 0.88, 0.50 and 0.12.
    window = make_window(detector_factory=Detector)
    make_images(folder, ["a.png"], IMAGE_SIZE)
    window.ui.confidence_slider.setValue(10)

    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "3")

    window.ui.confidence_slider.setValue(40)
    assert object_count(window) == "2"


MODEL_FILENAME = "tiny-detect.onnx"


def open_two_images(qtbot, window, folder, monkeypatch, detector_factory):
    """a.png holds a fish, b.png holds nothing. Returns the output folder."""
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH]
    window.ui.confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")
    return folder / "processed"


def test_crop_and_export_all_writes_crops_csv_and_settings(qtbot, window, folder, monkeypatch, detector_factory, toasts, spawned):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)

    window.ui.crop_and_export_all_images_action.trigger()

    assert (output / "a_crop.png").is_file()
    assert (output / "b_ncrop.png").is_file()
    assert (output / detections_csv_name(50, MODEL_FILENAME)).is_file()
    exported = json.loads((output / settings_json_name(50, MODEL_FILENAME)).read_text())
    assert set(exported["groups"]) == {"model", "crop"}
    assert int(exported["groups"]["model"]["confidence"]) == 50

    kind, title, text, kwargs = toasts[-1]
    assert (kind, title, text) == ("success", "Detectorist", "Finished cropping images.")
    assert kwargs["link_text"] == "Show in file manager"
    assert window.ui.open_output_folder_action.isEnabled()

    kwargs["on_link"]()
    assert spawned[-1][-1] == os.path.normpath(str(output))


def test_crop_and_export_selected_only_processes_the_selection(qtbot, window, folder, monkeypatch, detector_factory):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    select_row(window, 1)

    window.ui.crop_and_export_selected_images_action.trigger()

    assert sorted(path.name for path in output.glob("*.png")) == ["b_ncrop.png"]


def test_sort_by_class_copies_images_into_class_folders(qtbot, window, folder, monkeypatch, detector_factory, toasts):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)

    window.ui.group_images_by_object_class_action.trigger()

    assert (output / "Fish" / "a.png").is_file()
    assert (output / "no-detection" / "b.png").is_file()
    assert toasts[-1][2] == "Finished sorting images."


def test_batch_runs_respect_the_class_filter(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, CRAB]
    detector_factory.detections_by_file["b.png"] = [FISH]
    window.ui.confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "2")
    window.ui.class_filter_combo_box.setCurrentText("Crab")

    window.ui.group_images_by_object_class_action.trigger()

    # Without the filter the higher scoring fish would put both images into Fish/
    output = folder / "processed"
    assert (output / "Crab" / "a.png").is_file()
    assert (output / "no-detection" / "b.png").is_file()
    assert not (output / "Fish").exists()


def test_cancelling_a_batch_stops_it_without_a_success_toast(qtbot, window, folder, monkeypatch, detector_factory, toasts):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    # The batch detector runs on the GUI thread, so cancelling from inside
    # detect() is the same as the user pressing Cancel during the first image.
    detector_factory.on_detect = lambda _name: window.findChild(QProgressDialog).cancel()

    window.ui.crop_and_export_all_images_action.trigger()

    assert window.ui.status_bar.currentMessage() == "Cropping images cancelled."
    assert (output / "a_crop.png").is_file()
    assert not (output / "b_ncrop.png").exists()
    assert toasts == []
    assert not window.ui.open_output_folder_action.isEnabled()


def test_actions_are_disabled_while_a_batch_runs(qtbot, window, folder, monkeypatch, detector_factory):
    open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    guarded = [
        window.ui.open_folder_action,
        window.ui.open_images_action,
        window.ui.crop_and_export_all_images_action,
        window.ui.group_images_by_object_class_action,
        window.ui.clear_image_list_action,
    ]
    seen_during_run = []
    detector_factory.on_detect = lambda _name: seen_during_run.append([action.isEnabled() for action in guarded])

    window.ui.crop_and_export_all_images_action.trigger()

    assert seen_during_run == [[False] * len(guarded)] * 2
    assert all(action.isEnabled() for action in guarded)


def test_batch_whose_model_fails_to_load_reports_it_and_restores_the_actions(qtbot, window, folder, monkeypatch, detector_factory, toasts):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    detector_factory.error = OSError("boom")

    window.ui.crop_and_export_all_images_action.trigger()

    assert window.ui.status_bar.currentMessage() == "Error during Cropping images: boom"
    assert not output.exists()
    assert toasts == []
    assert window.ui.crop_and_export_all_images_action.isEnabled()
    assert window.ui.open_folder_action.isEnabled()


def test_closing_persists_the_controls_and_a_new_window_restores_them(make_window, settings):
    first = make_window()
    first.ui.confidence_slider.setValue(42)
    first.ui.padding_slider.setValue(7)
    first.ui.crop_ratio_combo_box.setCurrentIndex(3)
    first.ui.rb_crop_union.setChecked(True)
    first.ui.cb_comp_cam_exposure.setChecked(False)

    first.close()

    assert settings.confidence == 42
    assert settings.padding == 7
    assert settings.aspect_ratio_index == 3
    assert settings.crop_mode == "union"
    assert settings.auto_correct_exposure_enabled is False
    assert settings.model == MODEL_FILENAME
    assert settings.version == __version__

    second = make_window()

    assert second.ui.confidence_slider.value() == 42
    assert second.ui.padding_slider.value() == 7
    assert second.ui.crop_ratio_combo_box.currentIndex() == 3
    assert second.ui.rb_crop_union.isChecked()
    assert not second.ui.cb_comp_cam_exposure.isChecked()


def test_saved_model_is_selected_again(make_window, settings, models_dir):
    # Sorts before the saved model, so being first in the list is not enough
    (models_dir / "another.onnx").write_bytes(b"model")
    settings.model = MODEL_FILENAME

    window = make_window()

    assert window.ui.model_select_combo_box.currentData() == MODEL_FILENAME
    assert window.ui.model_select_combo_box.count() == 2


def write_manifest_superseding(models_dir, new_filename, old_filename):
    (models_dir / "models.json").write_text(json.dumps([
        {"name": "Tiny Detect", "url": f"https://example.invalid/{new_filename}", "supersedes": [old_filename]},
    ]))


def test_selection_follows_a_model_across_its_update(make_window, qtbot, models_dir, detector_factory):
    # Sorts before both versions, so it is what a lost selection would fall back to
    (models_dir / "another.onnx").write_bytes(b"model")
    write_manifest_superseding(models_dir, "tiny-detect-v2.onnx", MODEL_FILENAME)
    window = make_window()
    window.ui.model_select_combo_box.setCurrentIndex(window.ui.model_select_combo_box.findData(MODEL_FILENAME))

    # What a finished update download leaves behind
    (models_dir / "tiny-detect-v2.onnx").write_bytes(b"model")
    (models_dir / MODEL_FILENAME).unlink()
    window._refresh_model_list()

    assert window.ui.model_select_combo_box.currentData() == "tiny-detect-v2.onnx"
    qtbot.waitUntil(lambda: os.path.basename(detector_factory.created[-1].model_path) == "tiny-detect-v2.onnx")


def test_saved_model_that_was_superseded_selects_its_successor(make_window, settings, models_dir):
    (models_dir / "another.onnx").write_bytes(b"model")
    write_manifest_superseding(models_dir, MODEL_FILENAME, "tiny-detect-v0.onnx")
    settings.model = "tiny-detect-v0.onnx"

    window = make_window()

    assert window.ui.model_select_combo_box.currentData() == MODEL_FILENAME


def test_saved_model_that_is_gone_falls_back_to_an_available_one(make_window, settings, models_dir, detector_factory):
    (models_dir / "another.onnx").write_bytes(b"model")
    settings.model = "deleted-model.onnx"

    window = make_window()

    assert window.ui.model_select_combo_box.currentData() == "another.onnx"
    assert os.path.basename(detector_factory.created[0].model_path) == "another.onnx"


def test_export_settings_writes_model_and_crop_groups(window, tmp_path, monkeypatch):
    target = tmp_path / "exported.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    window.ui.confidence_slider.setValue(42)

    window.ui.export_settings_action.trigger()

    exported = json.loads(target.read_text())
    assert set(exported["groups"]) == {"model", "crop"}
    assert int(exported["groups"]["model"]["confidence"]) == 42
    assert window.ui.status_bar.currentMessage() == "Settings exported."


def test_import_settings_applies_them_to_the_controls(window, tmp_path, monkeypatch):
    source = tmp_path / "import.json"
    source.write_text(json.dumps({"groups": {"model": {"confidence": 33}, "crop": {"padding": 12, "mode": "union"}}}))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))

    window.ui.import_settings_action.trigger()

    assert window.ui.confidence_slider.value() == 33
    assert window.ui.padding_slider.value() == 12
    assert window.ui.rb_crop_union.isChecked()
    assert window.ui.status_bar.currentMessage() == "Settings imported."


def test_import_settings_loads_the_imported_model(window, qtbot, tmp_path, monkeypatch, models_dir, detector_factory):
    (models_dir / "another.onnx").write_bytes(b"model")
    window._refresh_model_list()
    assert window.ui.model_select_combo_box.currentData() == MODEL_FILENAME
    source = tmp_path / "import.json"
    source.write_text(json.dumps({"groups": {"model": {"path": "another.onnx"}}}))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))

    window.ui.import_settings_action.trigger()

    assert window.ui.model_select_combo_box.currentData() == "another.onnx"
    # The combo box alone is not enough, the worker has to switch models too
    qtbot.waitUntil(lambda: os.path.basename(detector_factory.created[-1].model_path) == "another.onnx")


def test_import_settings_keeps_the_window_layout(window, tmp_path, monkeypatch):
    window.resize(900, 700)
    window._save_settings()
    window.resize(1000, 800)
    source = tmp_path / "import.json"
    source.write_text(json.dumps({"groups": {"model": {"confidence": 33}}}))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))

    window.ui.import_settings_action.trigger()

    assert (window.width(), window.height()) == (1000, 800)


@pytest.mark.parametrize("content", ["this is not json", "[]"])
def test_importing_a_file_that_is_not_a_settings_file_reports_an_error(window, tmp_path, monkeypatch, toasts, content):
    source = tmp_path / "import.json"
    source.write_text(content)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    window.ui.confidence_slider.setValue(42)

    window.ui.import_settings_action.trigger()

    assert toasts[-1][:2] == ("error", "Could not import settings")
    assert window.ui.confidence_slider.value() == 42


def test_cancelled_import_dialog_changes_nothing(window, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    window.ui.confidence_slider.setValue(42)

    window.ui.import_settings_action.trigger()

    assert window.ui.confidence_slider.value() == 42


@pytest.mark.parametrize(("answer", "restored"), [
    (QMessageBox.StandardButton.Yes, True),
    (QMessageBox.StandardButton.No, False),
])
def test_reset_settings_restores_the_defaults_only_when_confirmed(window, monkeypatch, settings, answer, restored):
    default_confidence = window.ui.confidence_slider.value()
    default_padding = window.ui.padding_slider.value()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: answer)
    window.ui.confidence_slider.setValue(11)
    window.ui.padding_slider.setValue(44)
    window.ui.rb_crop_union.setChecked(True)

    window.ui.reset_settings_action.trigger()

    if restored:
        assert window.ui.confidence_slider.value() == default_confidence
        assert window.ui.padding_slider.value() == default_padding
        assert window.ui.rb_crop_all_detected_objects.isChecked()
        assert settings.confidence == default_confidence
    else:
        assert window.ui.confidence_slider.value() == 11
        assert window.ui.padding_slider.value() == 44
        assert window.ui.rb_crop_union.isChecked()


def recent_menu_texts(window) -> list[str]:
    return [action.text() for action in window.ui.recent_folders_menu.actions() if not action.isSeparator()]


def test_recent_folders_menu_lists_opened_folders_and_can_be_cleared(window, folder, monkeypatch, settings):
    assert recent_menu_texts(window)[0] == "No Recent Folders"
    make_images(folder, ["a.png"], IMAGE_SIZE)

    open_folder(window, folder, monkeypatch)
    assert recent_menu_texts(window)[0] == contract_user_path(str(folder))

    window.ui.clear_recent_folders_action.trigger()
    assert recent_menu_texts(window)[0] == "No Recent Folders"
    assert settings.recent_directories == []


def test_recent_folder_entry_opens_the_folder(make_window, folder, settings):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    settings.add_recent_directory(str(folder))
    window = make_window()

    window.ui.recent_folders_menu.actions()[0].trigger()

    assert listed(window) == ["a.png"]


def test_welcome_link_opens_the_recent_folder(make_window, folder, settings):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    settings.add_recent_directory(str(folder))
    window = make_window()
    assert str(folder) in window.ui.image_label.text()

    window.ui.image_label.linkActivated.emit(str(folder))

    assert listed(window) == ["a.png"]


def test_recent_folder_that_is_gone_warns_and_keeps_the_loaded_images(make_window, tmp_path, folder, monkeypatch, settings, toasts):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    settings.add_recent_directory(str(tmp_path / "unplugged"))
    window = make_window()
    open_folder(window, folder, monkeypatch)

    # The folder just opened is now first, the missing one second
    window.ui.recent_folders_menu.actions()[1].trigger()

    assert toasts[-1][:2] == ("warning", "Folder not found")
    assert listed(window) == ["a.png"]


def test_removing_the_selected_image_selects_its_neighbour(window, folder, monkeypatch):
    make_images(folder, ["a.png", "b.png", "c.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)
    select_row(window, 1)

    window.ui.remove_selected_images_from_list_action.trigger()

    assert listed(window) == ["a.png", "c.png"]
    assert window.ui.image_list_view.currentIndex().row() == 1


def test_removing_the_last_image_returns_to_the_welcome_state(window, folder, monkeypatch):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)

    window.ui.remove_selected_images_from_list_action.trigger()

    assert listed(window) == []
    assert "Drop images or a folder with images" in window.ui.image_label.text()
    assert not window.ui.clear_image_list_action.isEnabled()
    assert not window.ui.crop_and_export_all_images_action.isEnabled()


def test_clear_list_returns_to_the_welcome_state(window, folder, monkeypatch):
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)
    assert window.ui.clear_image_list_action.isEnabled()

    window.ui.clear_image_list_action.trigger()

    assert listed(window) == []
    assert "Drop images or a folder with images" in window.ui.image_label.text()
    assert not window.ui.crop_and_export_all_images_action.isEnabled()
    assert object_count(window) == "-"


def test_clear_list_disables_the_actions_that_need_a_selection(window, folder, monkeypatch):
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)

    window.ui.clear_image_list_action.trigger()

    assert not window.ui.crop_and_export_selected_images_action.isEnabled()
    assert not window.ui.remove_selected_images_from_list_action.isEnabled()


def test_copy_filenames_puts_them_on_the_clipboard(window, folder, monkeypatch, toasts):
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)

    window.ui.copy_filenames_to_clipboard_action.trigger()

    assert QApplication.clipboard().text() == "a.png"
    assert toasts[-1][:3] == ("success", "Copied to clipboard", "Copied 1 filename.")


def test_locate_reveals_the_image_in_the_file_manager(window, folder, monkeypatch, spawned):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)

    window.ui.locate_image_in_filemanager_action.trigger()

    # The command differs per platform (open -R, explorer /select, xdg-open
    # on the parent folder), but each one is handed a path inside the folder.
    assert any(os.path.normpath(str(folder)) in argument for argument in spawned[-1])


def test_copy_export_remove_does_all_three(qtbot, window, folder, monkeypatch, detector_factory):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)

    window.ui.copy_export_remove_action.trigger()

    assert QApplication.clipboard().text() == "a.png"
    assert (output / "a_crop.png").is_file()
    assert listed(window) == ["b.png"]
