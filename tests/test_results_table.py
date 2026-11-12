"""Tests for how the results table shows and sorts scores."""

import pytest
from PySide6.QtCore import Qt

from detectorist.export_planner import CropMode, CropSettings, plan_crops
from detectorist.results_table import BOX_ROLE, HEADER_LABELS, ResultsTable, format_score
from detectorist.structures import Detection, RankedName, Taxonomy


@pytest.mark.parametrize(("score", "expected"), [
    (0.0, "0.00"),
    (0.534, "0.53"),
    (0.987, "0.99"),
    # Would round to 1.00, which claims a certainty the model never has
    (0.9951, "0.99"),
    (0.9996, "0.99"),
    (1.0, "0.99"),
    # A family's score is a float32 sum of its species' probabilities and can pass 1
    (1.0000002, "0.99"),
])
def test_format_score_never_shows_one(score, expected):
    assert format_score(score) == expected


def taxonomy(species_score: float) -> Taxonomy:
    return Taxonomy(RankedName("Pomacentridae", 1.0), RankedName("Amphiprion", 1.0),
                    RankedName("Amphiprion_ocellaris", species_score))


def test_sorting_by_a_score_orders_by_the_score_rather_than_its_shown_text(qtbot):
    table = ResultsTable()
    qtbot.addWidget(table)
    # Both species show 0.99, the less confident detection has the higher species score
    confident = Detection((0, 0, 10, 10), 0.9, "Fish")
    best_classified = Detection((20, 0, 10, 10), 0.8, "Fish")
    taxonomy_by_box = {confident.box: taxonomy(0.9987), best_classified.box: taxonomy(0.9991)}
    detections = [confident, best_classified]
    table.show_detections(detections, taxonomy_by_box, threshold=0.5)
    species_score_column = HEADER_LABELS.index("List fit") - 1

    table.sortByColumn(species_score_column, Qt.SortOrder.DescendingOrder)
    settings = CropSettings(mode=CropMode.BEST_CLASSIFICATION, padding=0.0, aspect="detection_frame", taxon_confidence=0.5)
    [crop] = plan_crops(detections, 100, 100, settings, taxonomy_by_box)
    assert crop == best_classified.box
    assert table.topLevelItem(0).data(0, BOX_ROLE) == best_classified.box

    table.sortByColumn(species_score_column, Qt.SortOrder.AscendingOrder)
    assert table.topLevelItem(0).data(0, BOX_ROLE) == confident.box


def test_sorting_by_a_name_still_orders_by_its_text(qtbot):
    table = ResultsTable()
    qtbot.addWidget(table)
    detections = [Detection((0, 0, 10, 10), 0.9, "Fish"), Detection((20, 0, 10, 10), 0.8, "Crab")]
    table.show_detections(detections, {}, threshold=0.5)

    table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert [table.topLevelItem(i).text(0) for i in range(2)] == ["Crab", "Fish"]


def test_the_list_fit_column_shows_and_sorts_by_the_list_fit(qtbot):
    table = ResultsTable()
    qtbot.addWidget(table)
    table.set_list_fit_visible(True)
    likely_listed = Detection((0, 0, 10, 10), 0.9, "Fish")
    likely_unlisted = Detection((20, 0, 10, 10), 0.8, "Fish")
    # Named down to the family only, so the list fit follows empty genus and species cells
    family_only = Taxonomy(RankedName("Pomacentridae", 0.9), RankedName("Amphiprion", 0.1),
                           RankedName("Amphiprion_ocellaris", 0.1), list_fit=0.15)
    taxonomy_by_box = {likely_listed.box: taxonomy(0.9)._replace(list_fit=0.95), likely_unlisted.box: family_only}
    list_fit_column = HEADER_LABELS.index("List fit")

    table.show_detections([likely_listed, likely_unlisted], taxonomy_by_box, threshold=0.5)
    table.sortByColumn(list_fit_column, Qt.SortOrder.AscendingOrder)

    assert not table.isColumnHidden(list_fit_column)
    first = table.topLevelItem(0)
    assert first.data(0, BOX_ROLE) == likely_unlisted.box
    assert [first.text(c) for c in range(2, list_fit_column + 1)] == ["Pomacentridae", "0.90", "", "", "", "", "0.15"]


def test_the_list_fit_column_is_hidden_until_asked_for(qtbot):
    table = ResultsTable()
    qtbot.addWidget(table)

    assert table.isColumnHidden(HEADER_LABELS.index("List fit"))
    assert "species not on the list" in table.headerItem().toolTip(HEADER_LABELS.index("List fit"))
