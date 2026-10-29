"""Tests for the Batch Run.

The run goes through a real Pipeline, as in the app, with faked models
(they only need detect(image) and classify(image, boxes)) and tiny PNGs
written per test, so no ONNX model is involved.
"""

import codecs
import csv
import os
from dataclasses import replace

import pytest
from PIL import Image

from detectorist.batch_output import (
    CLASSIFICATION_CSV_HEADER,
    CLASSIFICATION_CSV_NAME,
    CSV_ENCODING,
    DETECTIONS_CSV_HEADER,
    DETECTIONS_CSV_NAME,
    ClassificationRow,
    DetectionsRow,
)
from detectorist.batch_run import BatchOptions, BatchWriter, CropExportAction
from detectorist.export_planner import CropMode, CropSettings, ExportOptions
from detectorist.image_object import ImageObject
from detectorist.pipeline import Pipeline
from detectorist.structures import Detection, RankedName, Taxonomy
from tests.fakes import FakeClassifier, FakeDetector, make_images

CROP_SETTINGS = CropSettings(mode=CropMode.MOST_CONFIDENT_DETECTION, padding=0.0, aspect=(1, 1))


def always_continue(index, total, filename):
    return True


@pytest.fixture
def run_batch(qtbot, tmp_path_factory):
    """
    Runs a Batch Run through a Pipeline holding the given models and returns
    its BatchResult. progress is called as each image starts, and returning
    False cancels the run, the way the progress dialog's Cancel does.
    """
    models_dir = tmp_path_factory.mktemp("models")
    for name in ("detector.onnx", "classifier.onnx"):
        (models_dir / name).write_bytes(b"model")

    def run(image_paths, detector, detection_confidence, output_dir, action, progress,
            class_filter=None, classifier=None, taxon_confidence=0.0):
        writer = BatchWriter(output_dir, action, classifier is not None,
                             classifier.patterns if classifier is not None else (), taxon_confidence)
        writer.open()
        pipeline = Pipeline(lambda _path: detector, lambda _path, _patterns: classifier)
        try:
            pipeline.load_detector(str(models_dir / "detector.onnx"))
            if classifier is not None:
                pipeline.load_classifier(str(models_dir / "classifier.onnx"), list(classifier.patterns))
            outcome = []
            pipeline.batch_finished.connect(outcome.append)
            pipeline.batch_failed.connect(outcome.append)

            def on_progress(index, total, name):
                if not progress(index, total, name):
                    pipeline.cancel_batch_run()

            pipeline.batch_progress.connect(on_progress)
            pipeline.start_batch_run(image_paths, BatchOptions(detection_confidence, class_filter),
                                     writer)
            qtbot.waitUntil(lambda: bool(outcome))
        finally:
            pipeline.shutdown()
        return outcome[0]

    return run


def read_detections_csv_rows(output_dir):
    with open(os.path.join(output_dir, DETECTIONS_CSV_NAME), newline="", encoding=CSV_ENCODING) as f:
        return list(csv.reader(f))


def test_crop_export_run(tmp_path, run_batch):
    paths = make_images(tmp_path, ["with_fish.png", "empty.png"])
    detector = FakeDetector({"with_fish.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5,
                       output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                       progress=always_continue)

    assert not result.cancelled
    assert os.path.isfile(os.path.join(output_dir, "Fish_with_fish_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "no-detection_empty.png"))
    assert read_detections_csv_rows(output_dir) == [
        DETECTIONS_CSV_HEADER,
        ["with_fish.png", "0.9", "Fish", "1", "yes"],
        ["empty.png", "0", "N/A", "0", "no"],
    ]


def test_source_image_aspect_is_resolved_per_image(tmp_path, run_batch):
    landscape = make_images(tmp_path, ["landscape.png"], size=(60, 40))
    portrait = make_images(tmp_path, ["portrait.png"], size=(40, 60))
    box = [Detection((10, 10, 20, 20), 0.9, "Fish")]
    detector = FakeDetector({"landscape.png": box, "portrait.png": box})
    output_dir = str(tmp_path / "out")
    settings = CropSettings(mode=CropMode.MOST_CONFIDENT_DETECTION, padding=0.0, aspect="source_image")

    run_batch(landscape + portrait, detector, detection_confidence=0.5,
              output_dir=output_dir, action=CropExportAction(ExportOptions(settings)),
              progress=always_continue)

    with Image.open(os.path.join(output_dir, "Fish_landscape_crop.png")) as crop:
        assert crop.size == (30, 20)
    with Image.open(os.path.join(output_dir, "Fish_portrait_crop.png")) as crop:
        assert crop.size == (20, 30)


def test_detections_below_confidence_are_dropped(tmp_path, run_batch):
    paths = make_images(tmp_path, ["faint.png"])
    detector = FakeDetector({"faint.png": [Detection((10, 10, 20, 20), 0.4, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5,
                       output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                       progress=always_continue)

    assert result.detections_rows == [("faint.png", 0, "N/A", 0, "no")]
    assert os.path.isfile(os.path.join(output_dir, "no-detection_faint.png"))


def test_class_filter_drops_detections_of_other_classes(tmp_path, run_batch):
    paths = make_images(tmp_path, ["both.png", "fish_only.png"])
    fish = Detection((10, 10, 20, 20), 0.9, "Fish")
    crab = Detection((30, 20, 10, 10), 0.8, "Crab")
    detector = FakeDetector({"both.png": [fish, crab], "fish_only.png": [fish]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5,
                       output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                       progress=always_continue, class_filter="Crab")

    # The crab wins although the fish scores higher. An image without a crab counts as empty
    assert result.detections_rows == [
        ("both.png", 0.8, "Crab", 1, "yes"),
        ("fish_only.png", 0, "N/A", 0, "no"),
    ]
    with Image.open(os.path.join(output_dir, "Crab_both_crop.png")) as crop:
        assert crop.size == (10, 10)
    assert os.path.isfile(os.path.join(output_dir, "no-detection_fish_only.png"))


@pytest.mark.parametrize(("detections", "cropped", "row"), [
    ([], False, ("a.png", 0, "N/A", 0, "no")),
    ([Detection((0, 0, 1, 1), 0.6, "Crab"), Detection((0, 0, 1, 1), 0.9, "Fish")], True, ("a.png", 0.9, "Fish", 2, "yes")),
    # Detected, but the action did not crop (Sort by Class, or no usable crop rectangle)
    ([Detection((0, 0, 1, 1), 0.9, "Fish")], False, ("a.png", 0.9, "Fish", 1, "no")),
])
def test_detections_row_reports_the_top_detection_and_the_crop(detections, cropped, row):
    assert DetectionsRow.from_detections("a.png", detections, cropped) == row


def test_load_failure_skips_image_and_continues(tmp_path, run_batch):
    paths = make_images(tmp_path, ["good_a.png", "good_b.png"])
    # A nonexistent file makes ImageObject.create raise
    paths.insert(1, str(tmp_path / "missing.png"))
    detector = FakeDetector({"good_a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5,
                       output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                       progress=always_continue)

    assert not result.cancelled
    assert result.detections_rows == [
        ("good_a.png", 0.9, "Fish", 1, "yes"),
        ("missing.png", 0, "load-error", 0, "n/a"),
        ("good_b.png", 0, "N/A", 0, "no"),
    ]
    assert result.failed == ["missing.png"]
    assert os.path.isfile(os.path.join(output_dir, "Fish_good_a_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "no-detection_good_b.png"))


def test_processing_failure_skips_image_and_continues(tmp_path, run_batch):
    paths = make_images(tmp_path, ["good_a.png", "bad.png", "good_b.png"])

    def fail_on_bad(name):
        if name == "bad.png":
            raise ValueError("boom")

    detector = FakeDetector({"good_a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, on_detect=fail_on_bad)
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5,
                       output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                       progress=always_continue)

    assert not result.cancelled
    assert result.detections_rows == [
        ("good_a.png", 0.9, "Fish", 1, "yes"),
        ("bad.png", 0, "process-error", 0, "n/a"),
        ("good_b.png", 0, "N/A", 0, "no"),
    ]
    assert result.failed == ["bad.png"]
    assert read_detections_csv_rows(output_dir)[2] == ["bad.png", "0", "process-error", "0", "n/a"]
    assert os.path.isfile(os.path.join(output_dir, "no-detection_good_b.png"))


def test_detection_without_area_is_exported_uncropped(tmp_path, run_batch):
    paths = make_images(tmp_path, ["flat.png"])
    detector = FakeDetector({"flat.png": [Detection((10, 10, 20, 0), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5,
                       output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                       progress=always_continue)

    assert result.detections_rows == [("flat.png", 0.9, "Fish", 1, "no")]
    assert result.failed == []
    with Image.open(os.path.join(output_dir, "Fish_flat.png")) as copy:
        assert copy.size == (64, 48)


def test_progress_can_cancel_the_run(tmp_path, run_batch):
    paths = make_images(tmp_path, ["a.png", "b.png", "c.png"])
    detector = FakeDetector({})
    output_dir = str(tmp_path / "out")
    seen = []

    def cancel_after_first(index, total, filename):
        seen.append((index, total, filename))
        return index < 1

    result = run_batch(paths, detector, detection_confidence=0.5,
                       output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                       progress=cancel_after_first)

    assert result.cancelled
    assert seen == [(0, 3, "a.png"), (1, 3, "b.png")]
    assert len(result.detections_rows) == 1  # only a.png was processed
    # The CSV still holds what was processed before the cancel
    assert len(read_detections_csv_rows(output_dir)) == 2  # header + a.png


def test_second_run_replaces_the_csv_of_the_first(tmp_path, run_batch):
    output_dir = str(tmp_path / "out")

    paths = make_images(tmp_path, ["a.png", "b.png"])
    detector = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.6, "Fish")]})
    run_batch(paths, detector, detection_confidence=0.5,
              output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
              progress=always_continue)

    detector2 = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.95, "Fish")]})
    run_batch([paths[0]], detector2, detection_confidence=0.5,
              output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
              progress=always_continue)

    # b.png is not in the second run, so its row is gone, while its copy stays
    assert read_detections_csv_rows(output_dir) == [DETECTIONS_CSV_HEADER, ["a.png", "0.95", "Fish", "1", "yes"]]
    assert os.path.isfile(os.path.join(output_dir, "no-detection_b.png"))


def test_csv_is_utf8_with_bom_and_keeps_non_latin_filenames(tmp_path, run_batch):
    # Names outside the Windows cp1252 code page, which the CSV used to be written in there
    paths = make_images(tmp_path, ["рыба.png", "魚.png"])
    output_dir = str(tmp_path / "out")

    run_batch(paths, FakeDetector(), detection_confidence=0.5,
              output_dir=output_dir, action=CropExportAction(ExportOptions(CROP_SETTINGS)),
              progress=always_continue)

    with open(os.path.join(output_dir, DETECTIONS_CSV_NAME), "rb") as f:
        raw = f.read()
    # The byte order mark is what lets Excel detect UTF-8
    assert raw.startswith(codecs.BOM_UTF8)
    assert [row[0] for row in read_detections_csv_rows(output_dir)] == ["Filename", "рыба.png", "魚.png"]


def test_unwritable_csv_fails_before_any_image_is_processed(tmp_path, run_batch):
    paths = make_images(tmp_path, ["a.png"])
    output_dir = tmp_path / "out"
    # A directory in the CSV's place cannot be opened for writing on any platform
    (output_dir / DETECTIONS_CSV_NAME).mkdir(parents=True)
    detector = FakeDetector()

    with pytest.raises(OSError, match=f"Cannot write {DETECTIONS_CSV_NAME}"):
        run_batch(paths, detector, detection_confidence=0.5,
                  output_dir=str(output_dir), action=CropExportAction(ExportOptions(CROP_SETTINGS)),
                  progress=always_continue)

    assert detector.detected == []
    assert not (output_dir / "no-detection_a.png").exists()


def read_classification_csv_rows(output_dir):
    with open(os.path.join(output_dir, CLASSIFICATION_CSV_NAME), newline="", encoding=CSV_ENCODING) as f:
        return list(csv.reader(f))


def run_classified_sort(run_batch, tmp_path, detections_by_file, classifier, taxon_confidence=0.0):
    """Export the images named in detections_by_file uncropped with a classifier. Returns the BatchResult."""
    paths = make_images(tmp_path, list(detections_by_file))
    action = CropExportAction(ExportOptions(replace(CROP_SETTINGS, taxon_confidence=taxon_confidence), crop=False,
                                            prefix_class=False, prefix_taxa=True,
                                            classifier_patterns=classifier.patterns if classifier else None))
    return run_batch(paths, FakeDetector(detections_by_file), detection_confidence=0.5,
                     output_dir=str(tmp_path / "out"), action=action,
                     progress=always_continue, classifier=classifier, taxon_confidence=taxon_confidence)


def test_detections_row_has_a_field_per_csv_column():
    assert len(DetectionsRow._fields) == len(DETECTIONS_CSV_HEADER)


def test_classification_row_has_a_field_per_csv_column():
    assert len(ClassificationRow._fields) == len(CLASSIFICATION_CSV_HEADER)


def test_every_named_detection_gets_a_classification_row(tmp_path, run_batch):
    detections = [Detection((30, 20, 10, 10), 0.8, "Fish"), Detection((10, 10, 20, 20), 0.9, "Fish")]

    run_classified_sort(run_batch, tmp_path, {"a.png": detections}, FakeClassifier())

    names = ["Pomacentridae", "0.99", "Amphiprion", "0.97", "Amphiprion_ocellaris", "0.44"]
    assert read_classification_csv_rows(str(tmp_path / "out")) == [
        CLASSIFICATION_CSV_HEADER,
        ["a.png", "1", "Fish", "0.9", "10", "10", "20", "20", *names],
        ["a.png", "2", "Fish", "0.8", "30", "20", "10", "10", *names],
    ]


def test_a_crowded_image_gets_a_classification_row_per_detection(tmp_path, run_batch):
    detections = [Detection((i, 0, 1, 1), 0.9, "Fish") for i in range(35)]

    result = run_classified_sort(run_batch, tmp_path, {"a.png": detections}, FakeClassifier())

    assert result.detections_rows[0].object_count == 35
    assert len(result.classification_rows) == 35


def test_detections_sharing_a_box_each_get_a_classification_row(tmp_path, run_batch):
    detections = [Detection((10, 10, 20, 20), 0.9, "Fish"), Detection((10, 10, 20, 20), 0.7, "Fish")]

    result = run_classified_sort(run_batch, tmp_path, {"a.png": detections}, FakeClassifier())

    assert [(row.detection, row.score) for row in result.classification_rows] == [(1, 0.9), (2, 0.7)]


def test_detections_csv_keeps_its_columns_with_a_classifier(tmp_path, run_batch):
    run_classified_sort(run_batch, tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, FakeClassifier())

    assert read_detections_csv_rows(str(tmp_path / "out")) == [DETECTIONS_CSV_HEADER, ["a.png", "0.9", "Fish", "1", "no"]]


@pytest.mark.parametrize(("taxon_confidence", "names"), [
    (0.5, ["Pomacentridae", 0.99, "Amphiprion", 0.97, "", ""]),
    (0.98, ["Pomacentridae", 0.99, "", "", "", ""]),
    # Not identified at all, but still counted
    (1.0, ["", "", "", "", "", ""]),
])
def test_ranks_below_the_taxon_confidence_are_left_empty(tmp_path, taxon_confidence, names, run_batch):
    result = run_classified_sort(run_batch, tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]},
                                 FakeClassifier(), taxon_confidence)

    (row,) = result.classification_rows
    assert [row.family, row.family_score, row.genus, row.genus_score, row.species, row.species_score] == names


def test_classification_rows_cover_only_the_classes_the_classifier_names(tmp_path, run_batch):
    crab, fish = Detection((10, 10, 20, 20), 0.9, "Crab"), Detection((30, 20, 10, 10), 0.8, "Fish")

    result = run_classified_sort(run_batch, tmp_path, {"a.png": [crab, fish]}, FakeClassifier(patterns=("Fish",)))

    assert [(row.filename, row.detection, row.class_name) for row in result.classification_rows] == [("a.png", 1, "Fish")]


def test_classification_boxes_are_clamped_to_the_image(tmp_path, run_batch):
    # The images are 64 x 48
    result = run_classified_sort(run_batch, tmp_path, {"a.png": [Detection((-5, 40, 20, 20), 0.9, "Fish")]}, FakeClassifier())

    (row,) = result.classification_rows
    assert (row.x, row.y, row.w, row.h) == (0, 40, 15, 8)


def test_without_a_classifier_no_classification_csv_is_written(tmp_path, run_batch):
    run_classified_sort(run_batch, tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, None)

    assert not (tmp_path / "out" / CLASSIFICATION_CSV_NAME).exists()


def test_without_a_classifier_a_leftover_classification_csv_is_removed(tmp_path, run_batch):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / CLASSIFICATION_CSV_NAME).write_text("from an earlier export")

    run_classified_sort(run_batch, tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, None)

    assert not (tmp_path / "out" / CLASSIFICATION_CSV_NAME).exists()


def test_a_failing_classifier_marks_the_classification_rows_of_the_image(tmp_path, run_batch):
    classifier = FakeClassifier(error=RuntimeError("out of memory"))
    detections = [Detection((10, 10, 20, 20), 0.9, "Fish"), Detection((30, 20, 10, 10), 0.8, "Fish")]

    result = run_classified_sort(run_batch, tmp_path, {"a.png": detections}, classifier)

    assert result.failed == []
    assert result.detections_rows == [("a.png", 0.9, "Fish", 2, "no")]
    names = ["classify-error", "", "", "", "", ""]
    assert read_classification_csv_rows(str(tmp_path / "out")) == [
        CLASSIFICATION_CSV_HEADER,
        ["a.png", "1", "Fish", "0.9", "10", "10", "20", "20", *names],
        ["a.png", "2", "Fish", "0.8", "30", "20", "10", "10", *names],
    ]
    assert (tmp_path / "out" / "unidentified_a.png").is_file()


def test_second_run_replaces_the_classification_csv_of_the_first(tmp_path, run_batch):
    two_fish = [Detection((10, 10, 5, 5), 0.9, "Fish"), Detection((30, 10, 5, 5), 0.8, "Fish")]
    run_classified_sort(run_batch, tmp_path, {"a.png": two_fish, "b.png": two_fish[:1]}, FakeClassifier())

    run_classified_sort(run_batch, tmp_path, {"a.png": two_fish[1:]}, FakeClassifier())

    rows = read_classification_csv_rows(str(tmp_path / "out"))
    assert [row[:5] for row in rows[1:]] == [["a.png", "1", "Fish", "0.8", "30"]]


def test_best_classification_crop_follows_the_classifier(tmp_path, run_batch):
    genus_only = Detection((5, 5, 10, 10), 0.9, "Fish")
    species = Detection((30, 10, 20, 16), 0.7, "Fish")
    classifier = FakeClassifier(taxonomy_by_box={
        genus_only.box: Taxonomy(RankedName("Pomacentridae", 0.99), RankedName("Amphiprion", 0.97), RankedName("Amphiprion_ocellaris", 0.48)),
        species.box: Taxonomy(RankedName("Pomacentridae", 0.90), RankedName("Amphiprion", 0.70), RankedName("Amphiprion_clarkii", 0.55)),
    })
    paths = make_images(tmp_path, ["a.png"])
    settings = CropSettings(mode=CropMode.BEST_CLASSIFICATION, padding=0.0, aspect="detection_frame", taxon_confidence=0.5)

    run_batch(paths, FakeDetector({"a.png": [genus_only, species]}), detection_confidence=0.5,
              output_dir=str(tmp_path / "out"),
              action=CropExportAction(ExportOptions(settings)), progress=always_continue, classifier=classifier, taxon_confidence=0.5)

    with Image.open(tmp_path / "out" / "Fish_a_crop.png") as crop:
        assert crop.size == (20, 16)


def test_best_classification_crop_falls_back_to_the_detection_when_the_classifier_fails(tmp_path, run_batch):
    paths = make_images(tmp_path, ["a.png"])
    detections = [Detection((5, 5, 10, 10), 0.9, "Fish"), Detection((30, 10, 20, 16), 0.7, "Fish")]
    settings = CropSettings(mode=CropMode.BEST_CLASSIFICATION, padding=0.0, aspect="detection_frame", taxon_confidence=0.5)

    run_batch(paths, FakeDetector({"a.png": detections}), detection_confidence=0.5,
              output_dir=str(tmp_path / "out"),
              action=CropExportAction(ExportOptions(settings)), progress=always_continue,
              classifier=FakeClassifier(error=RuntimeError("out of memory")), taxon_confidence=0.5)

    with Image.open(tmp_path / "out" / "Fish_a_crop.png") as crop:
        assert crop.size == (10, 10)


def test_an_image_that_fails_to_load_has_no_classification_rows(tmp_path, run_batch):
    run_batch([str(tmp_path / "missing.png")], FakeDetector(), detection_confidence=0.5,
              output_dir=str(tmp_path / "out"), action=CropExportAction(ExportOptions(CROP_SETTINGS)),
              progress=always_continue, classifier=FakeClassifier())

    assert read_classification_csv_rows(str(tmp_path / "out")) == [CLASSIFICATION_CSV_HEADER]


FISH = Detection((10, 10, 20, 20), 0.9, "Fish")
SPECIES = Taxonomy(RankedName("Pomacentridae", 0.99), RankedName("Amphiprion", 0.97),
                   RankedName("Amphiprion_ocellaris", 0.9))
GENUS_ONLY = SPECIES._replace(species=RankedName("Amphiprion_ocellaris", 0.3))
SORT_CROP_SETTINGS = replace(CROP_SETTINGS, taxon_confidence=0.5)
OTHER = Detection((40, 10, 10, 10), 0.8, "Fish")


def export(run_batch, tmp_path, paths, detector, classifier, crop=True, crop_settings=SORT_CROP_SETTINGS, prefix=(False, True)):
    """
    Export the images into tmp_path/out, named by taxon when there is a classifier, else by class.
    prefix is the pair of prefix_class and prefix_taxa. Returns the BatchResult.
    """
    prefix_class, prefix_taxa = prefix
    action = CropExportAction(ExportOptions(crop_settings, crop=crop, prefix_class=prefix_class, prefix_taxa=prefix_taxa,
                                            classifier_patterns=classifier.patterns if classifier else None))
    return run_batch(paths, detector, detection_confidence=0.5,
                     output_dir=str(tmp_path / "out"), action=action,
                     progress=always_continue, classifier=classifier, taxon_confidence=crop_settings.taxon_confidence)


def exported(tmp_path):
    return sorted(path.name for path in (tmp_path / "out").iterdir() if not path.name.endswith(".csv"))


def test_identified_crop_is_named_by_its_taxa(tmp_path, run_batch):
    export(run_batch, tmp_path, make_images(tmp_path, ["fish.png"]), FakeDetector({"fish.png": [FISH]}), FakeClassifier(SPECIES))

    assert exported(tmp_path) == ["Pomacentridae_Amphiprion_ocellaris_fish_crop.png"]


def test_partly_identified_crop_names_the_ranks_it_reached(tmp_path, run_batch):
    export(run_batch, tmp_path, make_images(tmp_path, ["fish.png"]), FakeDetector({"fish.png": [FISH]}), FakeClassifier(GENUS_ONLY))

    assert exported(tmp_path) == ["Pomacentridae_Amphiprion_unidentified_fish_crop.png"]


def test_each_object_crops_are_named_by_their_own_detection(tmp_path, run_batch):
    classifier = FakeClassifier(taxonomy_by_box={FISH.box: SPECIES, OTHER.box: GENUS_ONLY})
    crop_settings = replace(SORT_CROP_SETTINGS, mode=CropMode.EACH_OBJECT)

    export(run_batch, tmp_path, make_images(tmp_path, ["fish.png"]), FakeDetector({"fish.png": [FISH, OTHER]}), classifier,
           crop_settings=crop_settings)

    assert exported(tmp_path) == ["Pomacentridae_Amphiprion_ocellaris_fish_crop_0.png",
                                  "Pomacentridae_Amphiprion_unidentified_fish_crop_1.png"]


def test_a_failed_classification_names_the_crop_unidentified(tmp_path, run_batch):
    export(run_batch, tmp_path, make_images(tmp_path, ["fish.png"]), FakeDetector({"fish.png": [FISH]}),
           FakeClassifier(error=RuntimeError("out of memory")))

    assert exported(tmp_path) == ["unidentified_fish_crop.png"]


def test_a_class_the_classifier_does_not_name_keeps_its_class_name(tmp_path, run_batch):
    crab = Detection((10, 10, 20, 20), 0.9, "Crab")

    export(run_batch, tmp_path, make_images(tmp_path, ["a.png"]), FakeDetector({"a.png": [crab]}), FakeClassifier(patterns=("Fish",)))

    assert exported(tmp_path) == ["Crab_a_crop.png"]


def test_unsafe_class_names_are_made_safe(tmp_path, run_batch):
    odd = Detection((10, 10, 20, 20), 0.9, "Sea star/urchin")

    export(run_batch, tmp_path, make_images(tmp_path, ["a.png"]), FakeDetector({"a.png": [odd]}), None)

    assert exported(tmp_path) == ["Sea star_urchin_a_crop.png"]


@pytest.mark.parametrize("classifier", [None, FakeClassifier(SPECIES)])
def test_image_without_detections_is_copied_as_no_detection(tmp_path, classifier, run_batch):
    export(run_batch, tmp_path, make_images(tmp_path, ["empty.png"]), FakeDetector({}), classifier)

    assert exported(tmp_path) == ["no-detection_empty.png"]


def test_detection_only_crops_are_named_by_class(tmp_path, run_batch):
    export(run_batch, tmp_path, make_images(tmp_path, ["fish.png", "empty.png"]), FakeDetector({"fish.png": [FISH]}), None)

    assert exported(tmp_path) == ["Fish_fish_crop.png", "no-detection_empty.png"]


def test_uncropped_export_copies_each_image_once_named_by_its_detection(tmp_path, run_batch):
    classifier = FakeClassifier(taxonomy_by_box={FISH.box: SPECIES, OTHER.box: GENUS_ONLY})
    crop_settings = replace(SORT_CROP_SETTINGS, mode=CropMode.EACH_OBJECT)

    result = export(run_batch, tmp_path, make_images(tmp_path, ["fish.png"]), FakeDetector({"fish.png": [FISH, OTHER]}),
                    classifier, crop=False, crop_settings=crop_settings)

    assert exported(tmp_path) == ["Pomacentridae_Amphiprion_ocellaris_fish.png"]
    with Image.open(tmp_path / "out" / "Pomacentridae_Amphiprion_ocellaris_fish.png") as copy:
        assert copy.size == (64, 48)
    assert result.detections_rows[0].cropped == "no"


def test_reexport_overwrites_same_named_crops_and_keeps_the_rest(tmp_path, run_batch):
    paths = make_images(tmp_path, ["fish.png"])
    detector, classifier = FakeDetector({"fish.png": [FISH]}), FakeClassifier(GENUS_ONLY)
    unidentified = tmp_path / "out" / "Pomacentridae_Amphiprion_unidentified_fish_crop.png"

    export(run_batch, tmp_path, paths, detector, classifier)
    unidentified.write_bytes(b"stale")
    export(run_batch, tmp_path, paths, detector, classifier)
    assert unidentified.read_bytes() != b"stale"

    # A lower taxon confidence names the species, so the crop gets another name and the earlier one stays
    export(run_batch, tmp_path, paths, detector, classifier, crop_settings=replace(SORT_CROP_SETTINGS, taxon_confidence=0.2))
    assert exported(tmp_path) == ["Pomacentridae_Amphiprion_ocellaris_fish_crop.png",
                                  "Pomacentridae_Amphiprion_unidentified_fish_crop.png"]


@pytest.mark.parametrize(("prefix", "expected"), [
    ((True, False), ["Fish_fish_crop.png", "no-detection_empty.png"]),
    ((True, True), ["Fish_Pomacentridae_Amphiprion_ocellaris_fish_crop.png", "no-detection_empty.png"]),
    ((False, False), ["empty.png", "fish_crop.png"]),
])
def test_export_with_a_classifier_can_name_by_class_and_taxa_or_keep_the_names(tmp_path, prefix, expected, run_batch):
    export(run_batch, tmp_path, make_images(tmp_path, ["fish.png", "empty.png"]), FakeDetector({"fish.png": [FISH]}),
           FakeClassifier(SPECIES), prefix=prefix)

    assert exported(tmp_path) == expected


def test_writer_close_cancelled_keeps_rows_written(tmp_path):
    (path,) = make_images(tmp_path, ["a.png"])
    writer = BatchWriter(str(tmp_path / "out"), CropExportAction(ExportOptions(CROP_SETTINGS)),
                         with_classification=False, patterns=[], taxon_confidence=0.0)
    writer.open()
    writer.write(path, ImageObject.create(path), [], {})
    writer.write_failure(str(tmp_path / "gone.png"))

    result = writer.close(cancelled=True)

    assert result.cancelled
    assert result.failed == ["gone.png"]
    assert read_detections_csv_rows(str(tmp_path / "out"))[1:] == [
        ["a.png", "0", "N/A", "0", "no"],
        ["gone.png", "0", "load-error", "0", "n/a"],
    ]


@pytest.mark.parametrize("exposure_correction", [False, True])
def test_crop_export_action_saves_crops_with_its_exposure_choice(tmp_path, monkeypatch, exposure_correction):
    (path,) = make_images(tmp_path, ["a.png"])
    image = ImageObject.create(path)
    saved = []
    monkeypatch.setattr(image, "save_cropped", lambda rect, output_path, correct: saved.append(correct))
    action = CropExportAction(ExportOptions(CROP_SETTINGS), exposure_correction)
    action.prepare(str(tmp_path))

    assert action.process(image, [Detection((10, 10, 20, 20), 0.9, "Fish")], {})
    assert saved == [exposure_correction]
