"""Tests for the main window, DetectoristApp.

A real window is built with a file-backed Settings, a temp models folder and
a fake detector factory. The DetectionWorker and its QThread are real, so
the signal wiring between window and worker is what runs in production.

Tests act through actions and widgets and assert on what the user would see
(labels, bands, list contents, files on disk, recorded toasts). Modal
dialogs are replaced per test with monkeypatch.
"""

import csv
import json
import os

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPointF, QRect, Qt, QUrl
from PySide6.QtGui import QDropEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

from detectorist import __version__, detectorist_app
from detectorist.batch_output import classification_csv_name, detections_csv_name, settings_json_name
from detectorist.detection_style import MASK_COLORS
from detectorist.detector import Detector
from detectorist.image_label import DETECTION_BORDER_COLOR_RGB
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
    """The number of objects in the results summary, "-" while none is shown."""
    return window.ui.results_summary_label.text().split(" ")[0] or "-"


def result_rows(window) -> list[list[str]]:
    """The filled cells of each row of the results table, top to bottom."""
    table = window.ui.results_table
    rows = (table.topLevelItem(i) for i in range(table.topLevelItemCount()))
    return [[item.text(c) for c in range(table.columnCount()) if item.text(c)] for item in rows]


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


@pytest.fixture
def unreadable(monkeypatch, tmp_path):
    """A folder whose listing fails the way it does without read permission."""
    locked = tmp_path / "locked"
    locked.mkdir()
    real_listing = detectorist_app.list_supported_images

    def listing(folder_path):
        if folder_path == str(locked):
            raise PermissionError(13, "Permission denied", folder_path)
        return real_listing(folder_path)

    monkeypatch.setattr(detectorist_app, "list_supported_images", listing)
    return locked


def test_opening_an_unreadable_folder_warns_and_keeps_the_image_list(window, folder, unreadable, monkeypatch, settings, toasts):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)

    open_folder(window, unreadable, monkeypatch)

    kind, title, text, _ = toasts[-1]
    assert (kind, title) == ("warning", "Could not open folder")
    assert text.endswith("Permission denied")
    assert listed(window) == ["a.png"]
    assert settings.recent_directories == [str(folder)]


def test_dropping_an_unreadable_folder_warns_and_still_loads_dropped_files(window, folder, unreadable, toasts):
    paths = make_images(folder, ["a.png"], IMAGE_SIZE)

    drop(window, [unreadable, paths[0]])

    assert toasts[-1][:2] == ("warning", "Could not open folder")
    assert listed(window) == ["a.png"]


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
    window.ui.detection_confidence_slider.setValue(50)

    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    assert len(window.ui.image_label.detection_bands) == 1
    assert result_rows(window) == [["Fish", "0.90"]]


def test_lowering_the_confidence_reveals_detections_without_a_new_inference(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, FAINT_FISH]
    window.ui.detection_confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    window.ui.detection_confidence_slider.setValue(30)

    assert object_count(window) == "2"
    assert detector_factory.created[0].detected == ["a.png"]


def test_class_filter_restricts_the_shown_detections(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, CRAB]
    window.ui.detection_confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "2")

    window.ui.class_filter_combo_box.setCurrentText("Crab")

    assert object_count(window) == "1"
    assert [name for _rect, _score, name in window.ui.image_label.orig_detection_rects] == ["Crab"]


def test_selecting_another_image_shows_its_detections(qtbot, window, folder, monkeypatch, detector_factory):
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH]
    window.ui.detection_confidence_slider.setValue(50)
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
    window.ui.detection_confidence_slider.setValue(50)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "1")

    # What a late answer from the worker looks like after the user moved on
    window.handle_detection_complete(str(folder / "earlier.png"), [FISH, CRAB], 1.0)

    assert object_count(window) == "1"


@pytest.mark.parametrize(("radio_name", "expected"), [
    ("rb_crop_all_detected_objects", [QRect(20, 20, 40, 40), QRect(120, 50, 60, 40)]),
    ("rb_crop_most_confident_detection", [QRect(20, 20, 40, 40)]),
    ("rb_crop_union", [QRect(20, 20, 160, 70)]),
    ("rb_crop_centered_obj", [QRect(120, 50, 60, 40)]),
])
def test_crop_bands_follow_the_crop_mode(qtbot, window, folder, monkeypatch, detector_factory, radio_name, expected):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH, CRAB]
    window.ui.detection_confidence_slider.setValue(50)
    # No padding and the detection's own aspect ratio make the crop equal the box
    window.ui.padding_slider.setValue(0)
    window.ui.crop_ratio_combo_box.setCurrentText("Same as detection frame")
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "2")

    getattr(window.ui, radio_name).setChecked(True)

    assert window.ui.image_label.last_crop_rects == expected
    assert len(window.ui.image_label.crop_bands) == len(expected)


@pytest.mark.parametrize("is_segmentation", [True, False])
def test_mask_action_is_enabled_only_for_segmentation_models(make_window, detector_factory, is_segmentation):
    detector_factory.is_segmentation = is_segmentation

    window = make_window()

    assert window.ui.toggle_masks_action.isEnabled() == is_segmentation


def test_show_hide_all_hides_every_enabled_overlay_then_shows_them_again(make_window, detector_factory):
    detector_factory.is_segmentation = True
    window = make_window()
    ui = window.ui
    # Only the masks and boxes are enabled, as no classifier is selected
    ui.toggle_boxes_action.setChecked(False)

    ui.toggle_all_overlays_action.trigger()

    assert not ui.toggle_masks_action.isChecked()
    assert not ui.toggle_boxes_action.isChecked()
    assert ui.toggle_labels_action.isChecked()
    assert not ui.image_label._masks_visible

    ui.toggle_all_overlays_action.trigger()

    assert ui.toggle_masks_action.isChecked()
    assert ui.toggle_boxes_action.isChecked()
    assert ui.image_label._boxes_visible


def test_unreadable_image_reports_an_error(qtbot, window, folder, monkeypatch, toasts):
    (folder / "broken.png").write_bytes(b"this is not a png")

    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: len(toasts) == 1)

    kind, title, text, _kwargs = toasts[0]
    assert (kind, title) == ("error", "Could not process image")
    assert text.startswith("broken.png: ")
    assert window.ui.image_label.text().startswith("Error: ")
    assert window.ui.results_table.isHidden()


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
    window.ui.detection_confidence_slider.setValue(10)

    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) == "3")

    window.ui.detection_confidence_slider.setValue(40)
    assert object_count(window) == "2"


MODEL_FILENAME = "tiny-detect.onnx"


def open_two_images(qtbot, window, folder, monkeypatch, detector_factory):
    """a.png holds a fish, b.png holds nothing. Returns the output folder."""
    make_images(folder, ["a.png", "b.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = [FISH]
    window.ui.detection_confidence_slider.setValue(50)
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
    window.ui.detection_confidence_slider.setValue(50)
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


def fail_detection_of(detector_factory, bad_name):
    """Makes the detector of the next batch run raise for one image."""
    def on_detect(name):
        if name == bad_name:
            raise ValueError("boom")
    detector_factory.on_detect = on_detect


def test_batch_with_a_failing_image_finishes_and_warns(qtbot, window, folder, monkeypatch, detector_factory, toasts):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    fail_detection_of(detector_factory, "a.png")

    window.ui.crop_and_export_all_images_action.trigger()

    # The image after the failing one is still exported
    assert (output / "b_ncrop.png").is_file()
    kind, title, text, kwargs = toasts[-1]
    csv_name = detections_csv_name(50, MODEL_FILENAME)
    assert (kind, text) == ("warning", f"Finished cropping images, but 1 image failed. See {csv_name} for details.")
    assert kwargs["duration"] == 0
    assert kwargs["link_text"] == "Show in file manager"


def test_copy_export_remove_keeps_the_images_when_one_failed(qtbot, window, folder, monkeypatch, detector_factory):
    open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    fail_detection_of(detector_factory, "a.png")
    window.ui.image_list_view.selectAll()

    window.ui.copy_export_remove_action.trigger()

    assert listed(window) == ["a.png", "b.png"]


def test_batch_whose_model_fails_to_load_reports_it_and_restores_the_actions(qtbot, window, folder, monkeypatch, detector_factory, toasts):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    detector_factory.error = OSError("boom")

    window.ui.crop_and_export_all_images_action.trigger()

    assert window.ui.status_bar.currentMessage() == "Error during Cropping images: boom"
    assert not output.exists()
    assert [toast[:3] for toast in toasts] == [("error", "Cropping images failed", "boom")]
    assert window.ui.crop_and_export_all_images_action.isEnabled()
    assert window.ui.open_folder_action.isEnabled()


def test_closing_persists_the_controls_and_a_new_window_restores_them(make_window, settings):
    first = make_window()
    first.ui.detection_confidence_slider.setValue(42)
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

    assert second.ui.detection_confidence_slider.value() == 42
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
    window.ui.detection_confidence_slider.setValue(42)

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

    assert window.ui.detection_confidence_slider.value() == 33
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
    window.ui.detection_confidence_slider.setValue(42)

    window.ui.import_settings_action.trigger()

    assert toasts[-1][:2] == ("error", "Could not import settings")
    assert window.ui.detection_confidence_slider.value() == 42


def test_cancelled_import_dialog_changes_nothing(window, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    window.ui.detection_confidence_slider.setValue(42)

    window.ui.import_settings_action.trigger()

    assert window.ui.detection_confidence_slider.value() == 42


@pytest.mark.parametrize(("answer", "restored"), [
    (QMessageBox.StandardButton.Yes, True),
    (QMessageBox.StandardButton.No, False),
])
def test_reset_settings_restores_the_defaults_only_when_confirmed(window, monkeypatch, settings, answer, restored):
    default_confidence = window.ui.detection_confidence_slider.value()
    default_padding = window.ui.padding_slider.value()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: answer)
    window.ui.detection_confidence_slider.setValue(11)
    window.ui.padding_slider.setValue(44)
    window.ui.rb_crop_union.setChecked(True)

    window.ui.reset_settings_action.trigger()

    if restored:
        assert window.ui.detection_confidence_slider.value() == default_confidence
        assert window.ui.padding_slider.value() == default_padding
        assert window.ui.rb_crop_all_detected_objects.isChecked()
        assert settings.confidence == default_confidence
    else:
        assert window.ui.detection_confidence_slider.value() == 11
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


def test_results_are_only_shown_alongside_an_image(qtbot, window, folder, monkeypatch):
    assert window.ui.results_table.isHidden()

    make_images(folder, ["a.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: not window.ui.results_table.isHidden())

    window.ui.clear_image_list_action.trigger()

    assert window.ui.results_table.isHidden()


def test_toggling_exposure_correction_after_clear_list_keeps_the_welcome_state(qtbot, window, folder, monkeypatch):
    make_images(folder, ["a.png"], IMAGE_SIZE)
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: not window.ui.image_label.pixmap().isNull())
    window.ui.clear_image_list_action.trigger()

    window.ui.cb_comp_cam_exposure.toggle()

    assert window.ui.image_label.pixmap().isNull()
    assert "Drop images" in window.ui.image_label.text()


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


def tooltips(window) -> list[str]:
    return [band.toolTip() for band in window.ui.image_label.detection_bands]


def open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, detections):
    """Open a folder with one image, select the classifier and wait until the top detection is named."""
    make_images(folder, ["a.png"], IMAGE_SIZE)
    detector_factory.detections_by_file["a.png"] = detections
    open_folder(window, folder, monkeypatch)
    qtbot.waitUntil(lambda: object_count(window) != "-")
    window.ui.classifier_combo_box.setCurrentIndex(1)
    qtbot.waitUntil(lambda: tooltips(window)[0].startswith("Pomacentridae"))


def test_classifier_file_is_offered_apart_from_the_detection_models(species_model, window):
    models, classifiers = window.ui.model_select_combo_box, window.ui.classifier_combo_box

    assert [models.itemData(i) for i in range(models.count())] == [MODEL_FILENAME]
    assert [classifiers.itemData(i) for i in range(classifiers.count())] == [None, species_model]
    assert classifiers.itemText(1) == "Tiny Species"
    # Having one on disk does not switch it on
    assert classifiers.currentIndex() == 0


def test_classifier_the_manifest_does_not_know_is_offered_by_its_folder(models_dir, window):
    # E.g. one copied in by hand. Without a manifest entry it is taken to name every class.
    (models_dir / "classifiers").mkdir()
    (models_dir / "classifiers" / "mine.onnx").write_bytes(b"model")

    window._refresh_model_list()

    models, classifiers = window.ui.model_select_combo_box, window.ui.classifier_combo_box
    assert [models.itemData(i) for i in range(models.count())] == [MODEL_FILENAME]
    assert [classifiers.itemData(i) for i in range(classifiers.count())] == [None, "mine.onnx"]
    assert classifiers.itemText(1) == "mine"


def test_selecting_a_classifier_names_the_displayed_detections_in_their_tooltips(qtbot, species_model, window, folder, monkeypatch, detector_factory, classifier_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [FAINT_FISH, CRAB, FISH])

    # Above the confidence only, the highest scoring first
    assert classifier_factory.classified == [[FISH.box, CRAB.box]]
    assert classifier_factory.created[0].model_path == os.path.join(window.models_dir, "classifiers", species_model)
    # The species scores 0.44, below the default taxon confidence of 0.50
    assert tooltips(window) == ["Pomacentridae · Amphiprion 0.97"] * 2


def test_taxon_confidence_restyles_the_names_without_a_new_inference(qtbot, species_model, window, folder, monkeypatch, detector_factory, classifier_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [FISH])

    window.ui.taxon_confidence_spin_box.setValue(40)

    assert tooltips(window) == ["Pomacentridae · A. ocellaris 0.44"]
    assert len(classifier_factory.classified) == 1


def test_lowering_the_confidence_names_the_detections_it_reveals(qtbot, species_model, window, folder, monkeypatch, detector_factory, classifier_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [FISH, FAINT_FISH])
    assert tooltips(window)[1:] == []

    window.ui.detection_confidence_spin_box.setValue(10)

    qtbot.waitUntil(lambda: len(tooltips(window)) == 2 and tooltips(window)[1].startswith("Pomacentridae"))
    assert classifier_factory.classified == [[FISH.box], [FAINT_FISH.box]]


def test_dragging_the_confidence_asks_for_names_once(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [FISH, FAINT_FISH])
    requests = []
    window.request_classification.connect(lambda path, min_detection_score: requests.append(min_detection_score))

    for value in (40, 30, 20, 10):
        window.ui.detection_confidence_slider.setValue(value)

    qtbot.waitUntil(lambda: len(tooltips(window)) == 2 and tooltips(window)[1].startswith("Pomacentridae"))
    assert requests == [0.10]


def test_deselecting_the_classifier_shows_the_detector_class_again(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [FISH])

    window.ui.classifier_combo_box.setCurrentIndex(0)

    qtbot.waitUntil(lambda: tooltips(window) == ["Fish 0.90"])


def border_rgb(window) -> list[tuple]:
    return [band.border_color.getRgb()[:3] for band in window.ui.image_label.detection_bands]


def test_a_classifier_colors_the_detections_by_family_and_labels_them(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    labels = window.ui.toggle_labels_action
    assert not labels.isEnabled()

    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [FISH])

    # The only family in the image takes the first palette color
    assert border_rgb(window) == [MASK_COLORS[0]]
    assert labels.isEnabled()
    labels.trigger()
    assert not window.ui.image_label._labels_visible

    window.ui.classifier_combo_box.setCurrentIndex(0)

    qtbot.waitUntil(lambda: tooltips(window) == ["Fish 0.90"])
    assert border_rgb(window) == [DETECTION_BORDER_COLOR_RGB]
    assert not labels.isEnabled()


def test_results_list_each_detection_with_its_deepest_identified_rank(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [CRAB, FISH])

    # The highest score first, down to the deepest rank at or above the taxon confidence
    assert result_rows(window) == [["Fish", "0.90", "Pomacentridae", "0.99", "Amphiprion", "0.97"],
                                   ["Crab", "0.80", "Pomacentridae", "0.99", "Amphiprion", "0.97"]]

    window.ui.taxon_confidence_spin_box.setValue(40)

    assert result_rows(window)[0] == ["Fish", "0.90", "Pomacentridae", "0.99", "Amphiprion", "0.97",
                                      "Amphiprion ocellaris", "0.44"]

    window.ui.taxon_confidence_spin_box.setValue(100)

    assert result_rows(window)[0] == ["Fish", "0.90", "Unidentified"]


def test_results_summary_gives_the_detections_and_classifications_with_their_times(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [CRAB, FISH])
    window._last_detection_time_ms = 220.0

    window.handle_classification_complete(window.current_image_path, window._taxonomy_by_box, 430.0)

    assert window.ui.results_summary_label.text() == "2 objects detected (220 ms). 2 of them classified (430 ms)."

    # Only the shown detections are counted, the time stays that of every name of the image
    window.ui.class_filter_combo_box.setCurrentText("Fish")

    assert window.ui.results_summary_label.text() == "1 object detected (220 ms). 1 of them classified (430 ms)."


def test_hovering_a_detection_shows_its_result_row_in_bold(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [CRAB, FISH])
    table = window.ui.results_table

    def bold():
        return [table.topLevelItem(i).font(0).bold() for i in range(table.topLevelItemCount())]

    window.ui.image_label.detection_hovered.emit(CRAB.box)
    assert bold() == [False, True]

    window.ui.image_label.detection_hovered.emit(None)
    assert bold() == [False, False]

    # Rebuilds the rows
    window.ui.image_label.detection_hovered.emit(CRAB.box)
    window.ui.taxon_confidence_spin_box.setValue(40)
    assert bold() == [False, True]


def test_hovering_a_detection_or_refreshing_the_results_keeps_the_table_scrolled(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    fish = [Detection((10 * i, 10, 5, 5), 0.9 - i / 100, "Fish") for i in range(15)]
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, fish)
    table = window.ui.results_table
    # Shown and short, so the rows need a scroll bar
    table.setFixedHeight(80)
    window.show()
    qtbot.waitUntil(lambda: table.verticalScrollBar().maximum() > 0)
    scroll_bar = table.verticalScrollBar()
    scroll_bar.setValue(scroll_bar.maximum())

    # The first row is scrolled out of view
    window.ui.image_label.detection_hovered.emit(fish[0].box)
    assert scroll_bar.value() == scroll_bar.maximum()

    window.ui.taxon_confidence_spin_box.setValue(40)
    assert scroll_bar.value() == scroll_bar.maximum()


def test_hovering_a_detection_keeps_the_order_of_a_sorted_table(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [CRAB, FISH])
    table = window.ui.results_table
    # Both share the family, so the tie keeps the highest score first
    table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
    assert [row[0] for row in result_rows(window)] == ["Fish", "Crab"]

    for box in (CRAB.box, FISH.box, None, CRAB.box):
        window.ui.image_label.detection_hovered.emit(box)
        assert [row[0] for row in result_rows(window)] == ["Fish", "Crab"]

    table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
    assert [row[0] for row in result_rows(window)] == ["Fish", "Crab"]


def test_hovering_a_result_row_highlights_its_detection_across_a_refresh(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [CRAB, FISH])
    table = window.ui.results_table
    viewport = table.viewport()

    def highlighted():
        return [band.box for band in window.ui.image_label.detection_bands if band.highlighted]

    # Sent directly, as a window that is not shown on screen gets no mouse events
    point = QPointF(table.visualItemRect(table.topLevelItem(1)).center())
    QApplication.sendEvent(viewport, QMouseEvent(QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
                                                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert highlighted() == [CRAB.box]

    # Rebuilds the rows and the boxes
    window.ui.taxon_confidence_spin_box.setValue(40)
    assert highlighted() == [CRAB.box]

    QApplication.sendEvent(viewport, QEvent(QEvent.Type.Leave))
    assert highlighted() == []


def test_a_row_moving_under_a_resting_mouse_highlights_its_detection(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [CRAB, FISH])
    table = window.ui.results_table

    def highlighted():
        return [band.box for band in window.ui.image_label.detection_bands if band.highlighted]

    point = QPointF(table.visualItemRect(table.topLevelItem(0)).center())
    QApplication.sendEvent(table.viewport(), QMouseEvent(QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
                                                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert highlighted() == [FISH.box]

    # The Fish row goes, so the Crab row moves up under the mouse
    window.ui.class_filter_combo_box.setCurrentText("Crab")

    assert highlighted() == [CRAB.box]


def test_classifier_settings_and_columns_are_set_aside_without_a_classifier(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    assert not window.ui.taxon_confidence_slider.isEnabled()

    open_with_classifier(qtbot, window, folder, monkeypatch, detector_factory, [FISH])
    assert window.ui.taxon_confidence_slider.isEnabled()

    window.ui.classifier_combo_box.setCurrentIndex(0)

    assert not window.ui.taxon_confidence_slider.isEnabled()
    qtbot.waitUntil(lambda: result_rows(window) == [["Fish", "0.90"]])
    table = window.ui.results_table
    # Only the detector's class and confidence
    assert [table.isColumnHidden(c) for c in range(table.columnCount())] == [False, False] + [True] * 6


def test_classifier_that_fails_to_load_is_reported(qtbot, species_model, window, classifier_factory, toasts):
    classifier_factory.error = OSError("not a classifier")

    window.ui.classifier_combo_box.setCurrentIndex(1)

    qtbot.waitUntil(lambda: len(toasts) == 1)
    assert toasts[0][:3] == ("error", "Classifier error", "Error loading classifier: not a classifier")


def test_batch_with_a_classifier_writes_the_classification_csv(qtbot, species_model, window, folder, monkeypatch, detector_factory):
    output = open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    window.ui.classifier_combo_box.setCurrentIndex(1)
    window.ui.taxon_confidence_spin_box.setValue(50)

    window.ui.group_images_by_object_class_action.trigger()

    with open(output / classification_csv_name(50, species_model), newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    # Only a.png has a detection. The species scores below the taxon confidence
    assert [row[0] for row in rows[1:]] == ["a.png"]
    assert rows[1][8:] == ["Pomacentridae", "0.99", "Amphiprion", "0.97", "", "", "tiny-classify"]
    with open(output / detections_csv_name(50, MODEL_FILENAME), newline="", encoding="utf-8-sig") as f:
        assert len(next(csv.reader(f))) == 5


def test_batch_shares_the_classifier_of_the_worker(qtbot, species_model, window, folder, monkeypatch, detector_factory, classifier_factory):
    open_two_images(qtbot, window, folder, monkeypatch, detector_factory)
    window.ui.classifier_combo_box.setCurrentIndex(1)

    window.ui.group_images_by_object_class_action.trigger()

    assert len(classifier_factory.created) == 1


def test_classifier_and_taxon_confidence_are_restored_by_a_new_window(qtbot, species_model, make_window, settings):
    window = make_window()
    window.ui.classifier_combo_box.setCurrentIndex(1)
    window.ui.taxon_confidence_spin_box.setValue(30)
    window.close()

    restored = make_window()

    assert restored.ui.classifier_combo_box.currentData() == species_model
    assert restored.ui.taxon_confidence_slider.value() == 30


def test_saved_classifier_that_is_gone_leaves_none_selected(make_window, settings):
    settings.classifier = "deleted-classifier.onnx"

    window = make_window()

    assert window.ui.classifier_combo_box.currentData() is None


def test_reset_settings_deselects_the_classifier(species_model, window, monkeypatch):
    window.ui.classifier_combo_box.setCurrentIndex(1)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    window.ui.reset_settings_action.trigger()

    assert window.ui.classifier_combo_box.currentData() is None


def set_classifies(models_dir, patterns):
    """Rewrite the classifier manifest so its classifier names only detections of the given class patterns."""
    manifest_path = models_dir / "classifiers" / "models.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest:
        entry["classifies"] = patterns
    manifest_path.write_text(json.dumps(manifest))


def classifier_items(window) -> list:
    combo = window.ui.classifier_combo_box
    return [combo.itemData(i) for i in range(combo.count())]


@pytest.fixture
def bee_model(models_dir, detector_factory) -> str:
    """Adds a second detection model, one that reports bees. Returns the filename."""
    filename = "bee.onnx"
    (models_dir / filename).write_bytes(b"model")
    detector_factory.class_names_by_model[filename] = {1: "Apoidea"}
    return filename


def select_model(qtbot, window, filename, class_name):
    """Select a detection model and wait until it reported its classes."""
    combo = window.ui.model_select_combo_box
    combo.setCurrentIndex(combo.findData(filename))
    qtbot.waitUntil(lambda: window.ui.class_filter_combo_box.findText(class_name) >= 0)


def test_classifier_for_other_classes_is_not_offered(species_model, models_dir, make_window):
    set_classifies(models_dir, ["Apoidea"])

    window = make_window()

    assert classifier_items(window) == [None]
    assert not window.ui.classifier_combo_box.isEnabled()


def test_classifier_is_offered_when_a_pattern_matches_one_of_the_classes(species_model, models_dir, make_window):
    set_classifies(models_dir, ["Apoidea", "Fi*"])

    window = make_window()

    assert classifier_items(window) == [None, species_model]
    assert window.ui.classifier_combo_box.isEnabled()


def test_classifier_is_set_aside_for_a_model_it_does_not_apply_to_and_comes_back(qtbot, species_model, bee_model, models_dir, make_window, settings, classifier_factory):
    set_classifies(models_dir, ["Fish*"])
    window = make_window()
    select_model(qtbot, window, MODEL_FILENAME, "Fish")
    window.ui.classifier_combo_box.setCurrentIndex(1)

    select_model(qtbot, window, bee_model, "Apoidea")
    assert classifier_items(window) == [None]

    select_model(qtbot, window, MODEL_FILENAME, "Fish")
    assert window.ui.classifier_combo_box.currentData() == species_model
    qtbot.waitUntil(lambda: len(classifier_factory.created) == 2)

    # Closing while it is set aside still saves it as the choice
    select_model(qtbot, window, bee_model, "Apoidea")
    window.close()
    assert settings.classifier == species_model


def test_choosing_no_classifier_is_remembered_across_models(qtbot, species_model, bee_model, models_dir, make_window):
    set_classifies(models_dir, ["Fish*"])
    window = make_window()
    select_model(qtbot, window, MODEL_FILENAME, "Fish")
    window.ui.classifier_combo_box.setCurrentIndex(1)
    window.ui.classifier_combo_box.setCurrentIndex(0)

    select_model(qtbot, window, bee_model, "Apoidea")
    select_model(qtbot, window, MODEL_FILENAME, "Fish")

    assert window.ui.classifier_combo_box.currentIndex() == 0
