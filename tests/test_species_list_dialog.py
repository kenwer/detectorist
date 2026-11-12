"""Tests for the Species List dialog."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from detectorist.species_list_dialog import SpeciesListDialog
from tests.fakes import FakeClassifier

CHECKED, PARTIAL, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked, Qt.CheckState.Unchecked


def make_dialog(qtbot, species=()) -> SpeciesListDialog:
    dialog = SpeciesListDialog("Fake Fish", FakeClassifier(), species)
    qtbot.addWidget(dialog)
    return dialog


def tree_items(dialog):
    """The family, its genera and their species, as (item, [(genus, [species])])."""
    family = dialog.ui.species_tree.topLevelItem(0)
    genera = [family.child(i) for i in range(family.childCount())]
    return family, [(genus, [genus.child(i) for i in range(genus.childCount())]) for genus in genera]


def visible_texts(dialog) -> list[str]:
    texts = []

    def walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            if not child.isHidden():
                texts.append(child.text(0))
                walk(child)

    walk(dialog.ui.species_tree.invisibleRootItem())
    return texts


def test_the_tree_groups_species_by_family_and_genus_with_counts(qtbot):
    dialog = make_dialog(qtbot, ["Amphiprion_ocellaris"])

    family, [(amphiprion, [clarkii, ocellaris]), (chromis, [viridis])] = tree_items(dialog)

    assert family.text(0) == "Pomacentridae (1/3)"
    assert amphiprion.text(0) == "Amphiprion (1/2)"
    assert chromis.text(0) == "Chromis (0/1)"
    assert [clarkii.text(0), ocellaris.text(0), viridis.text(0)] == ["Amphiprion clarkii", "Amphiprion ocellaris",
                                                                    "Chromis viridis"]
    assert [family.checkState(0), amphiprion.checkState(0), ocellaris.checkState(0)] == [PARTIAL, PARTIAL, CHECKED]
    assert dialog.ui.count_label.text() == "1 of 3 species"


def test_ticking_a_genus_ticks_its_species_and_updates_the_counts(qtbot):
    dialog = make_dialog(qtbot)
    family, [(amphiprion, _), _] = tree_items(dialog)

    amphiprion.setCheckState(0, CHECKED)
    qtbot.waitUntil(lambda: dialog.ui.count_label.text() == "2 of 3 species")

    assert family.text(0) == "Pomacentridae (2/3)"
    assert dialog.species() == ["Amphiprion_clarkii", "Amphiprion_ocellaris"]


def test_clear_unticks_every_species(qtbot):
    dialog = make_dialog(qtbot, ["Amphiprion_ocellaris"])
    family, _ = tree_items(dialog)

    family.setCheckState(0, CHECKED)
    assert dialog.species() == FakeClassifier.species
    dialog._clear()
    assert dialog.species() == []


def test_species_the_classifier_does_not_know_are_ignored(qtbot):
    dialog = make_dialog(qtbot, ["Amphiprion_ocellaris", "Not_a_species"])

    assert dialog.species() == ["Amphiprion_ocellaris"]


def test_the_search_matches_family_genus_and_species(qtbot):
    dialog = make_dialog(qtbot)

    dialog.ui.search_line_edit.setText("chromis")
    assert visible_texts(dialog) == ["Pomacentridae (0/3)", "Chromis (0/1)", "Chromis viridis"]
    dialog.ui.search_line_edit.setText("pomacentridae")
    assert len(visible_texts(dialog)) == 6
    dialog.ui.search_line_edit.setText("clark")
    assert visible_texts(dialog)[-1] == "Amphiprion clarkii"


def test_show_selected_only_hides_the_unticked_species(qtbot):
    dialog = make_dialog(qtbot, ["Amphiprion_ocellaris"])

    dialog.ui.selected_only_check_box.setChecked(True)

    assert visible_texts(dialog) == ["Pomacentridae (1/3)", "Amphiprion (1/2)", "Amphiprion ocellaris"]
    _, [(amphiprion, _), _] = tree_items(dialog)
    assert amphiprion.isExpanded()


@pytest.mark.parametrize(("window_height", "dialog_height"), [(900, 720), (300, 320)])
def test_the_dialog_is_four_fifths_as_tall_as_its_window_but_not_below_its_minimum(qtbot, window_height,
                                                                                   dialog_height):
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(800, window_height)

    dialog = SpeciesListDialog("Fake Fish", FakeClassifier(), (), window)

    assert dialog.height() == dialog_height
