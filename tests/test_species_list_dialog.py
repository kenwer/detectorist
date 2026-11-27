"""Tests for the Species List dialog."""

from types import SimpleNamespace
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QTreeWidgetItem, QWidget

from detectorist import species_list_dialog
from detectorist.classifier import Classifier
from detectorist.species_list_dialog import SpeciesListDialog, _children, import_report
from detectorist.species_list_file import Matches
from detectorist.structures import Taxon
from tests.fakes import FakeClassifier, fake_classifier, present

CHECKED, PARTIAL, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked, Qt.CheckState.Unchecked


def make_dialog(qtbot, species=()) -> SpeciesListDialog:
    dialog = SpeciesListDialog("Fake Fish", fake_classifier(), species)
    qtbot.addWidget(dialog)
    return dialog


def tree_items(dialog) -> tuple[QTreeWidgetItem, list[tuple[QTreeWidgetItem, list[QTreeWidgetItem]]]]:
    """The family, its genera and their species, as (item, [(genus, [species])])."""
    family = present(dialog.ui.species_tree.topLevelItem(0))
    return family, [(genus, list(_children(genus))) for genus in _children(family)]


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


def test_checking_a_genus_checks_its_species_and_updates_the_counts(qtbot):
    dialog = make_dialog(qtbot)
    family, [(amphiprion, _), _] = tree_items(dialog)

    amphiprion.setCheckState(0, CHECKED)
    qtbot.waitUntil(lambda: dialog.ui.count_label.text() == "2 of 3 species")

    assert family.text(0) == "Pomacentridae (2/3)"
    assert dialog.species() == ["Amphiprion_clarkii", "Amphiprion_ocellaris"]


def test_clear_unchecks_every_species(qtbot):
    dialog = make_dialog(qtbot, ["Amphiprion_ocellaris"])
    family, _ = tree_items(dialog)

    family.setCheckState(0, CHECKED)
    assert dialog.species() == FakeClassifier.species
    dialog.ui.clear_button.click()
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


def test_show_checked_only_hides_the_unchecked_species(qtbot):
    dialog = make_dialog(qtbot, ["Amphiprion_ocellaris"])

    dialog.ui.checked_only_check_box.setChecked(True)

    assert visible_texts(dialog) == ["Pomacentridae (1/3)", "Amphiprion (1/2)", "Amphiprion ocellaris"]
    _, [(amphiprion, _), _] = tree_items(dialog)
    assert amphiprion.isExpanded()


def test_the_dialog_is_four_fifths_as_tall_as_its_window(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(800, 900)

    dialog = SpeciesListDialog("Fake Fish", fake_classifier(), (), window)

    assert dialog.height() == 720


def test_the_dialog_is_never_smaller_than_its_layout_needs(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(800, 100)

    dialog = SpeciesListDialog("Fake Fish", fake_classifier(), (), window)

    assert dialog.height() == dialog.minimumSizeHint().height()
    assert dialog.width() >= dialog.minimumSizeHint().width()


def test_the_dialog_widens_for_a_long_name_but_not_beyond_its_window(qtbot):
    long_name = "Pseudanthias_" + "x" * 80
    classifier = cast(Classifier, SimpleNamespace(taxa=[Taxon(long_name, "Pseudanthias", "Serranidae")]))
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(5000, 900)

    short = SpeciesListDialog("Fake Fish", fake_classifier(), (), window)
    long = SpeciesListDialog("Fake Fish", classifier, (), window)
    window.resize(400, 900)
    capped = SpeciesListDialog("Fake Fish", classifier, (), window)
    for dialog in (short, long, capped):
        qtbot.addWidget(dialog)

    metrics = long.ui.species_tree.fontMetrics()
    assert long.width() > short.width()
    assert long.width() > metrics.horizontalAdvance(long_name.replace("_", " ")) + 3 * long.ui.species_tree.indentation()
    assert capped.width() == max(400, capped.minimumSizeHint().width())


def test_import_adds_the_species_a_file_selects_to_the_checked_ones_and_tells_how_many(qtbot, monkeypatch,
                                                                                       tmp_path):
    source = tmp_path / "list.txt"
    source.write_text("# reef survey\nAmphiprion *\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    shown = []
    monkeypatch.setattr(species_list_dialog, "show_success_toast",
                        lambda parent, title, text, **kwargs: shown.append((title, text)))
    dialog = make_dialog(qtbot, ["Amphiprion_ocellaris", "Chromis_viridis"])

    dialog.ui.import_button.click()

    assert dialog.species() == ["Amphiprion_clarkii", "Amphiprion_ocellaris", "Chromis_viridis"]
    assert shown == [("Species list merged", "Added 1 species to the 2 already checked, making 3.")]


def test_clear_then_import_replaces_the_checked_species(qtbot, monkeypatch, tmp_path):
    source = tmp_path / "list.txt"
    source.write_text("Amphiprion clarkii\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    monkeypatch.setattr(species_list_dialog, "show_success_toast", lambda *args, **kwargs: None)
    dialog = make_dialog(qtbot, ["Chromis_viridis"])

    dialog.ui.clear_button.click()
    dialog.ui.import_button.click()

    assert dialog.species() == ["Amphiprion_clarkii"]


def test_import_warns_of_lines_matching_nothing_and_keeps_the_checked_species_if_none_match(qtbot, monkeypatch, tmp_path):
    source = tmp_path / "list.txt"
    source.write_text("Bombus terrestris\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    shown = []
    monkeypatch.setattr(species_list_dialog, "show_warning_toast",
                        lambda parent, title, text, **kwargs: shown.append((title, text, kwargs["duration"])))
    dialog = make_dialog(qtbot, ["Chromis_viridis"])

    dialog.ui.import_button.click()

    assert dialog.species() == ["Chromis_viridis"]
    assert shown == [("No species found to import", "The following species were not in Fake Fish:\n\n- *Bombus terrestris*", 0)]


def test_import_reads_a_file_that_is_not_utf_8(qtbot, monkeypatch, tmp_path):
    source = tmp_path / "list.txt"
    source.write_bytes("# Erfasst von J\u00fcrgen\nChromis viridis\n".encode("cp1252"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    dialog = make_dialog(qtbot, [])

    dialog.ui.import_button.click()

    assert dialog.species() == ["Chromis_viridis"]


def test_export_writes_the_checked_species_and_is_off_without_any(qtbot, monkeypatch, tmp_path):
    target = tmp_path / "out.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    dialog = make_dialog(qtbot, ["Chromis_viridis", "Amphiprion_ocellaris"])

    dialog.ui.export_button.click()

    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Species list for Fake Fish"
    assert lines[-2:] == ["Amphiprion ocellaris", "Chromis viridis"]
    dialog.ui.clear_button.click()
    qtbot.waitUntil(lambda: not dialog.ui.export_button.isEnabled())


def test_the_import_report_names_the_entries_not_found_escaped():
    matches = Matches(("Chromis_viridis",), ("Chromis virdis", "Dascyllus *", "Dascyllus_aruanus <3"))

    title, text = import_report(matches, (), "Fake Fish")

    assert title == "Species list imported"
    assert text.startswith("Checked 1 species from the file.\n\nThe following species were not in Fake Fish:")
    assert "*Chromis virdis*" in text
    assert "*Dascyllus \\**" in text
    assert "*Dascyllus\\_aruanus \\<3*" in text


@pytest.mark.parametrize(("species", "checked_before", "title", "text"), [
    (("Amphiprion_clarkii", "Chromis_viridis"), (), "Species list imported", "Checked 2 species from the file."),
    (("Amphiprion_clarkii", "Chromis_viridis"), ("Chromis_viridis", "Amphiprion_ocellaris"), "Species list merged",
     "Added 1 species to the 2 already checked, making 3."),
    (("Chromis_viridis",), ("Chromis_viridis",), "Species list merged", "Every species in the file was already checked."),
    ((), ("Chromis_viridis",), "No species found to import", "The file names no species."),
])
def test_the_import_report_tells_how_the_species_merged(species, checked_before, title, text):
    assert import_report(Matches(species, ()), checked_before, "Fake Fish") == (title, text)
