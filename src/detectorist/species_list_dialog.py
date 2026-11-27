"""The Species List dialog, which picks the species a classifier names."""

import datetime
import logging
import re
from collections import defaultdict
from collections.abc import Collection, Iterator
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QStyle, QTreeWidget, QTreeWidgetItem, QWidget

from . import species_list_file
from .classifier import Classifier, display_name
from .toasts import show_error_toast, show_success_toast, show_warning_toast
from .ui_species_list_dialog import Ui_SpeciesListDialog

logger = logging.getLogger(__name__)

# Where a species item keeps the model's Genus_species name
SPECIES_ROLE = Qt.ItemDataRole.UserRole
# Where a family or genus item keeps its name, as its text adds the count
NAME_ROLE = Qt.ItemDataRole.UserRole + 1
# Where a species item keeps the lowercase text the search matches: its family, genus and species
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 2
FILE_FILTER = "Species Lists (*.txt *.csv);;All Files (*)"


def import_report(matches: species_list_file.Matches, checked_before: Collection[str],
                  classifier_name: str) -> tuple[str, str]:
    """
    The title and Markdown text of the toast after an import: how the species
    it selects merged with those checked before, and the entries that
    selected none.
    """
    added = len(set(matches.species) - set(checked_before))
    if not matches.species:
        title, summary = "No species found to import", "" if matches.unmatched else "The file names no species."
    elif not checked_before:
        title, summary = "Species list imported", f"Checked {added} species from the file."
    elif not added:
        title, summary = "Species list merged", "Every species in the file was already checked."
    else:
        title = "Species list merged"
        summary = (f"Added {added} species to the {len(checked_before)} already checked, "
                   f"making {len(checked_before) + added}.")
    if not matches.unmatched:
        return title, summary
    # Escaped, so a glob's "*" is not read as Markdown emphasis
    items = ["- *" + re.sub(r"([\\`*_\[\]<>~])", r"\\\1", entry) + "*" for entry in matches.unmatched]
    unmatched = f"The following species were not in {classifier_name}:\n\n" + "\n".join(items)
    return title, f"{summary}\n\n{unmatched}" if summary else unmatched


def _with_count(name: str, checked: int, total: int) -> str:
    """The text of a family or genus item."""
    return f"{name} ({checked}/{total})"


def _children(item: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
    return (child for i in range(item.childCount()) if (child := item.child(i)) is not None)


class SpeciesListDialog(QDialog):
    """
    Lists every species a classifier knows as Family > Genus > Species, each
    with a checkbox. Checking a family or genus checks its species, also those
    the search hides, and a partly checked one shows how many are checked.
    No species checked means no species list. The checked species can be
    imported from and exported to a species list file (see species_list_file).
    """

    def __init__(self, classifier_name: str, classifier: Classifier, species: Collection[str],
                 parent: QWidget | None = None):
        """
        Args:
            classifier_name: Shown in the title.
            classifier: The loaded classifier, read for its taxonomy.
            species: The species checked at first. Names the classifier does
                not know are ignored.
        """
        super().__init__(parent)
        self.ui = Ui_SpeciesListDialog()
        self.ui.setupUi(self)
        self.setWindowTitle(f'Species list for "{classifier_name}"')
        self._classifier_name = classifier_name
        self._taxa = classifier.taxa

        self._species_items = self._fill_tree(set(species))
        self._fit_size(parent)
        self._update_counts()
        # Checking a family changes all its species, each signalling, so the counts are updated once after
        self._counts_timer = QTimer(self, singleShot=True, interval=0)
        self._counts_timer.timeout.connect(self._update_counts)
        self.ui.species_tree.itemChanged.connect(self._counts_timer.start)

        # Not on checking, so a species unchecked with Show checked only stays put under the mouse
        self.ui.search_line_edit.textChanged.connect(self._filter)
        self.ui.checked_only_check_box.toggled.connect(self._filter)
        self.ui.clear_button.clicked.connect(lambda: self._set_checked_species(()))
        self.ui.import_button.clicked.connect(self._import)
        self.ui.export_button.clicked.connect(self._export)

    def species(self) -> list[str]:
        """The checked species in the model's Genus_species form, in tree order."""
        return [item.data(0, SPECIES_ROLE) for item in self._species_items
                if item.checkState(0) == Qt.CheckState.Checked]

    def _fill_tree(self, checked: set[str]) -> list[QTreeWidgetItem]:
        """Adds the families, genera and species sorted by name. Returns the species items."""
        tree: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for taxon in self._taxa:
            tree[taxon.family][taxon.genus].append(taxon.species)

        def checkable(parent: QTreeWidget | QTreeWidgetItem, name: str, tristate: bool) -> QTreeWidgetItem:
            item = QTreeWidgetItem(parent, [name])
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags | Qt.ItemFlag.ItemIsAutoTristate if tristate else flags)
            # Set before the children are added, as setting a parent's state sets theirs
            item.setCheckState(0, Qt.CheckState.Unchecked)
            return item

        species_items: list[QTreeWidgetItem] = []
        # Families and genera are counted as all checked until _update_counts, so the dialog is sized for that
        for family in sorted(tree):
            family_total = sum(map(len, tree[family].values()))
            family_item = checkable(self.ui.species_tree, _with_count(family, family_total, family_total), tristate=True)
            family_item.setData(0, NAME_ROLE, family)
            for genus in sorted(tree[family]):
                genus_total = len(tree[family][genus])
                genus_item = checkable(family_item, _with_count(genus, genus_total, genus_total), tristate=True)
                genus_item.setData(0, NAME_ROLE, genus)
                for name in sorted(tree[family][genus]):
                    item = checkable(genus_item, display_name(name), tristate=False)
                    item.setData(0, SPECIES_ROLE, name)
                    item.setData(0, SEARCH_ROLE, f"{family} {genus} {display_name(name)}".lower())
                    if name in checked:
                        item.setCheckState(0, Qt.CheckState.Checked)
                    species_items.append(item)
        return species_items

    def _fit_size(self, parent: QWidget | None) -> None:
        """
        Sizes the dialog to show every tree row unclipped, never narrower than
        its layout needs nor wider than the window it belongs to, and tall
        enough to browse a family without much scrolling.
        """
        tree = self.ui.species_tree
        # Measured expanded and over every row, as collapsed rows do not count and by default only 1000 rows do
        tree.header().setResizeContentsPrecision(-1)
        tree.expandAll()
        rows_width = tree.sizeHintForColumn(0)
        tree.collapseAll()
        scroll_bar = tree.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, tree)
        margins = self.ui.verticalLayout.contentsMargins()
        width = rows_width + 2 * tree.frameWidth() + scroll_bar + margins.left() + margins.right()
        height = self.sizeHint().height()
        if parent is not None:
            window = parent.window()
            width, height = min(width, window.width()), round(window.height() * 0.8)
        # Last, as the layout would squeeze its buttons and resize() before showing does not stop it
        minimum = self.minimumSizeHint()
        self.resize(max(width, minimum.width()), max(height, minimum.height()))

    def _update_counts(self):
        """Shows "(checked/total)" after each family and genus, and the checked species of all below the tree."""
        checked_total = 0
        # Blocked, as each new text would signal itemChanged and start another update
        with QSignalBlocker(self.ui.species_tree):
            for family in _children(self.ui.species_tree.invisibleRootItem()):
                family_checked = family_total = 0
                for genus in _children(family):
                    checked = sum(item.checkState(0) == Qt.CheckState.Checked for item in _children(genus))
                    genus.setText(0, _with_count(genus.data(0, NAME_ROLE), checked, genus.childCount()))
                    family_checked += checked
                    family_total += genus.childCount()
                family.setText(0, _with_count(family.data(0, NAME_ROLE), family_checked, family_total))
                checked_total += family_checked
        self.ui.count_label.setText(f"{checked_total} of {len(self._species_items)} species")
        self.ui.export_button.setEnabled(checked_total > 0)

    def _filter(self):
        """
        Shows the species matching the search, only the checked ones with Show
        checked only, and the families and genera holding any of them.
        Filtering expands what it shows, except fully checked genera with Show
        checked only, which would repeat a whole genus.
        """
        needle = self.ui.search_line_edit.text().strip().lower()
        checked_only = self.ui.checked_only_check_box.isChecked()
        for family in _children(self.ui.species_tree.invisibleRootItem()):
            family_shown = False
            for genus in _children(family):
                genus_shown = False
                for item in _children(genus):
                    shown = ((not checked_only or item.checkState(0) == Qt.CheckState.Checked)
                             and needle in item.data(0, SEARCH_ROLE))
                    item.setHidden(not shown)
                    genus_shown |= shown
                genus.setHidden(not genus_shown)
                genus.setExpanded(bool(needle) or (checked_only and genus.checkState(0) == Qt.CheckState.PartiallyChecked))
                family_shown |= genus_shown
            family.setHidden(not family_shown)
            family.setExpanded(bool(needle) or checked_only)

    def _set_checked_species(self, species: Collection[str]) -> None:
        """
        Checks exactly the given species, in the model's Genus_species form.
        Unlike checking by hand, it filters again, so Show checked only shows
        the newly checked ones.
        """
        wanted = set(species)
        for item in self._species_items:
            item.setCheckState(0, Qt.CheckState.Checked if item.data(0, SPECIES_ROLE) in wanted else Qt.CheckState.Unchecked)
        self._filter()

    def _import(self) -> None:
        """
        Also checks the species a file the user picks selects, telling how many
        were added and of lines that select none.
        """
        # No folder given, so the native dialog opens where the user last picked a file
        path, _ = QFileDialog.getOpenFileName(self, "Add Species from File", "", FILE_FILTER)
        if not path:
            return
        try:
            # utf-8-sig, as Notepad and Excel start their UTF-8 files with a byte order mark. Errors replaced,
            # as Excel may save as cp1252, whose non-ASCII letters are in comments and authors, not names
            text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            self._file_error("Could not read species list", path, e)
            return
        matches = species_list_file.match(species_list_file.parse(text), self._taxa)
        checked_before = self.species()
        # Added to, not replaced, so smaller lists can be combined, with Clear first to replace
        if matches.species:
            self._set_checked_species({*checked_before, *matches.species})
        report = import_report(matches, checked_before, self._classifier_name)
        if matches.unmatched:
            # Kept until closed, as the names are needed to fix the file
            show_warning_toast(self, *report, duration=0, markdown=True)
        elif not matches.species:
            show_warning_toast(self, *report)
        else:
            show_success_toast(self, *report)

    def _export(self) -> None:
        """Saves the checked species to a file the user picks."""
        # The classifier name may hold characters a file name cannot
        stem = re.sub(r'[\\/:*?"<>|]', "_", f"{self._classifier_name} species list")
        path, _ = QFileDialog.getSaveFileName(self, "Save Species List", f"{stem}.txt", FILE_FILTER)
        if not path:
            return
        header = [f"Species list for {self._classifier_name}", f"Exported on {datetime.date.today().isoformat()}"]
        try:
            Path(path).write_text(species_list_file.format_list(self.species(), header), encoding="utf-8")
        except OSError as e:
            self._file_error("Could not save species list", path, e)

    def _file_error(self, title: str, path: str, error: Exception) -> None:
        logger.error("%s %s: %s", title, path, error)
        show_error_toast(self, title, f"{Path(path).name}: {error}")
