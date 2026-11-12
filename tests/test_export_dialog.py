import os

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog

from detectorist.export_dialog import ExportDialog, PreviewImage
from detectorist.export_planner import CropMode, CropSettings, ExportOptions
from detectorist.structures import Detection, RankedName, Taxonomy

FOLDER = os.path.abspath(os.path.join(os.sep, "photos", "reef A"))
IMAGES = [os.path.join(FOLDER, f"IMG_00{i}.jpg") for i in range(40, 44)]
RUN_FILES = ["detectorist-detections.csv", "detectorist-settings.json"]

FISH = Detection((10, 10, 40, 40), 0.9, "Fish")
# The shown image, IMG_0040, with one fish named to its species
PREVIEW_IMAGE = PreviewImage(IMAGES[0], [FISH], 100, 100, {FISH.box: Taxonomy(
    RankedName("Pomacentridae", 0.9), RankedName("Amphiprion", 0.9), RankedName("Amphiprion_ocellaris", 0.9))})


@pytest.fixture
def make_dialog(qtbot):
    def make(selected=(), has_classifier=True, crop=True, prefix_class=False, prefix_taxa=True, class_filter=None,
             skip_no_detection=False, skip_unidentified=False, preview_image=PREVIEW_IMAGE):
        options = ExportOptions(CropSettings(CropMode.EACH_OBJECT, 0.0, (1, 1)), crop=crop,
                                prefix_class=prefix_class, prefix_taxa=prefix_taxa,
                                has_classifier=has_classifier,
                                skip_no_detection=skip_no_detection, skip_unidentified=skip_unidentified)
        dialog = ExportDialog(IMAGES, list(selected), options=options, preview_image=preview_image,
                              run_files=RUN_FILES, class_filter=class_filter)
        qtbot.addWidget(dialog)
        return dialog
    return make


def preview(dialog) -> QTextDocument:
    document = QTextDocument()
    document.setHtml(dialog.ui.preview_label.text())
    return document


def preview_lines(dialog) -> list[str]:
    return preview(dialog).toPlainText().splitlines()


def export_button(dialog):
    return dialog.ui.button_box.button(QDialogButtonBox.StandardButton.Ok)


def test_export_button_counts_the_images_in_scope(make_dialog):
    dialog = make_dialog(IMAGES[1:2])
    assert export_button(dialog).text() == "Export 4 Images"

    dialog.ui.rb_selected.setChecked(True)

    assert export_button(dialog).text() == "Export 1 Image"


def test_preview_shows_all_its_lines(make_dialog, qtbot):
    dialog = make_dialog()
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.ui.preview_label.height() >= dialog.ui.preview_label.minimumSizeHint().height()


def test_dialog_is_only_as_tall_as_its_contents(make_dialog, qtbot):
    dialog = make_dialog()
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.height() == dialog.minimumSizeHint().height()


@pytest.mark.parametrize("selected", [(), IMAGES[:1]])
def test_scope_defaults_to_all_images_without_several_selected(make_dialog, selected):
    assert make_dialog(selected).images() == IMAGES


def test_scope_defaults_to_several_selected_images(make_dialog):
    dialog = make_dialog(IMAGES[1:3])
    assert dialog.images() == IMAGES[1:3]
    assert export_button(dialog).text() == "Export 2 Images"


def test_all_images_can_be_chosen_instead_of_several_selected(make_dialog):
    dialog = make_dialog(IMAGES[1:3])

    dialog.ui.rb_all.setChecked(True)

    assert dialog.images() == IMAGES
    assert export_button(dialog).text() == "Export 4 Images"


@pytest.mark.parametrize("selected", [IMAGES[:1], IMAGES[1:3]])
def test_the_selection_can_be_chosen_instead(make_dialog, selected):
    dialog = make_dialog(selected)

    dialog.ui.rb_selected.setChecked(True)

    assert dialog.images() == list(selected)


def test_the_selection_choice_is_disabled_without_selected_images(make_dialog):
    assert not make_dialog().ui.rb_selected.isEnabled()


def test_scope_labels_count_the_images(make_dialog):
    dialog = make_dialog(IMAGES[1:3])
    assert dialog.ui.rb_selected.text() == "Selected images (2)"
    assert dialog.ui.rb_all.text() == "All images (4)"


def test_choices_start_from_the_given_options(make_dialog):
    options = make_dialog(crop=False, prefix_class=True, prefix_taxa=False, skip_no_detection=True,
                          skip_unidentified=True).options()
    assert (options.crop, options.prefix_class, options.prefix_taxa) == (False, True, False)
    assert (options.skip_no_detection, options.skip_unidentified) == (True, True)


def test_taxa_is_unavailable_without_a_classifier_but_stays_chosen(make_dialog):
    dialog = make_dialog(has_classifier=False)
    assert not dialog.ui.cb_prefix_taxa.isEnabled()
    assert dialog.ui.cb_prefix_taxa.text() == "Taxa (no classifier)"
    assert dialog.options().prefix_taxa


def test_skipping_unidentified_is_offered_only_with_a_classifier_but_stays_chosen(make_dialog):
    assert not make_dialog().ui.cb_skip_unidentified.isHidden()
    dialog = make_dialog(has_classifier=False, skip_no_detection=True, skip_unidentified=True)
    assert dialog.ui.cb_skip_unidentified.isHidden()
    assert dialog.options().skip_unidentified


def test_skipping_unidentified_takes_skipping_images_without_detections(make_dialog):
    dialog = make_dialog()
    assert not dialog.ui.cb_skip_unidentified.isEnabled()
    dialog.ui.cb_skip_no_detection.setChecked(True)
    assert dialog.ui.cb_skip_unidentified.isEnabled()


@pytest.mark.parametrize(("preview_image", "name"), [
    (PreviewImage(IMAGES[0], [], 100, 100, {}), "no-detection_IMG_0040.jpg"),
    (PreviewImage(IMAGES[0], [FISH], 100, 100, {}), "unidentified_IMG_0040_crop.jpg"),
])
def test_example_names_the_files_of_an_image_the_skip_choices_leave_out(make_dialog, preview_image, name):
    dialog = make_dialog(skip_no_detection=True, skip_unidentified=True, preview_image=preview_image)
    assert f"    {name}" in preview_lines(dialog)


def test_output_defaults_to_processed_in_the_image_folder(make_dialog):
    assert make_dialog().output_dir() == os.path.join(FOLDER, "processed")


def test_choosing_a_folder_exports_there(make_dialog, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))
    dialog = make_dialog()

    dialog.ui.choose_button.click()

    assert dialog.output_dir() == str(tmp_path)
    assert not dialog.ui.default_link_label.isHidden()
    assert export_button(dialog).isEnabled()


def test_use_default_is_hidden_on_the_default_folder(make_dialog):
    assert make_dialog().ui.default_link_label.isHidden()


def test_use_default_returns_to_the_default_folder(make_dialog, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))
    dialog = make_dialog()
    dialog.ui.choose_button.click()

    dialog.ui.default_link_label.linkActivated.emit("default")

    assert dialog.output_dir() == os.path.join(FOLDER, "processed")
    assert dialog.ui.default_link_label.isHidden()


def test_a_folder_not_made_yet_is_shown_as_text(make_dialog):
    label = make_dialog().ui.output_path_label
    assert "<a " not in label.text()
    assert label.toolTip() == f"{os.path.join(FOLDER, 'processed')}\nCreated when exporting"


def test_an_existing_folder_is_a_link_that_opens_it(make_dialog, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    dialog = make_dialog()
    dialog.ui.choose_button.click()
    label = dialog.ui.output_path_label

    label.linkActivated.emit(label.text())

    assert "<a " in label.text()
    assert opened == [QUrl.fromLocalFile(str(tmp_path))]


def test_cancelling_the_folder_choice_keeps_the_default(make_dialog, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "")
    dialog = make_dialog()

    dialog.ui.choose_button.click()

    assert dialog.output_dir() == os.path.join(FOLDER, "processed")


def test_the_image_folder_itself_is_refused_as_output(make_dialog, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: FOLDER)
    dialog = make_dialog()

    dialog.ui.choose_button.click()

    assert not export_button(dialog).isEnabled()
    assert "image folder" in dialog.ui.note_label.text()


def test_the_class_filter_is_named_only_when_set(make_dialog):
    assert make_dialog().ui.class_filter_label.isHidden()
    dialog = make_dialog(class_filter="Fish")
    assert not dialog.ui.class_filter_label.isHidden()
    assert dialog.ui.class_filter_label.text() == "Only Fish detections (Show filter)"


def test_preview_shows_an_example_and_the_naming_scheme(make_dialog):
    assert preview_lines(make_dialog()) == [
        "Naming scheme:",
        "<output folder>",
        "    <Family>_<Genus>_<Species>_<Filename>_crop[_<n>].jpg",
        "    ...and 3 more images",
        "    detectorist-detections.csv",
        "    detectorist-settings.json",
        "",
        "Example:",
        "reef A/processed/",
        "    Pomacentridae_Amphiprion_ocellaris_IMG_0040_crop.jpg",
        "    ...and 3 more images",
        "    detectorist-detections.csv",
        "    detectorist-settings.json",
    ]


def test_preview_follows_the_choices(make_dialog):
    dialog = make_dialog()

    dialog.ui.cb_crop.setChecked(False)
    dialog.ui.cb_prefix_class.setChecked(True)
    dialog.ui.cb_prefix_taxa.setChecked(False)

    preview = preview_lines(dialog)
    assert "    Fish_IMG_0040.jpg" in preview
    assert "    <Class>_<Filename>.jpg" in preview


def test_preview_without_known_names_lists_the_image_count(make_dialog):
    dialog = make_dialog(IMAGES[1:3])

    dialog.ui.rb_selected.setChecked(True)

    preview = preview_lines(dialog)
    assert "    2 images" in preview


def test_preview_of_another_folder_starts_with_its_last_two_names(make_dialog, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))
    dialog = make_dialog()

    dialog.ui.choose_button.click()

    preview = preview_lines(dialog)
    assert preview[preview.index("Example:") + 1] == f"{tmp_path.parent.name}/{tmp_path.name}/"
