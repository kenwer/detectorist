"""The Species List dialog, which picks the species a classifier names."""

from collections import defaultdict
from collections.abc import Collection, Iterator

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QDialog, QTreeWidgetItem, QWidget

from .classifier import Classifier, display_name
from .ui_species_list_dialog import Ui_SpeciesListDialog

# Where a species item keeps the model's Genus_species name
SPECIES_ROLE = Qt.ItemDataRole.UserRole
# Where a family or genus item keeps its name, as its text adds the count
NAME_ROLE = Qt.ItemDataRole.UserRole + 1
# Where a species item keeps the lowercase text the search matches: its family, genus and species
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 2


def _children(item: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
    return (item.child(i) for i in range(item.childCount()))


class SpeciesListDialog(QDialog):
    """
    Lists every species a classifier knows as Family > Genus > Species, each
    with a checkbox. Ticking a family or genus ticks its species, also those
    the search hides, and a partly ticked one shows how many are ticked.
    No species ticked means no species list.
    """

    def __init__(self, classifier_name: str, classifier: Classifier, species: Collection[str],
                 parent: QWidget | None = None):
        """
        Args:
            classifier_name: Shown in the title.
            classifier: The loaded classifier, read for its taxonomy.
            species: The species ticked at first. Names the classifier does
                not know are ignored.
        """
        super().__init__(parent)
        self.ui = Ui_SpeciesListDialog()
        self.ui.setupUi(self)
        # Tall enough to browse a family without much scrolling, never taller than the window it belongs to
        if parent is not None:
            self.resize(self.width(), round(parent.window().height() * 0.8))
        self.setWindowTitle(f'Species list for "{classifier_name}"')

        self._species_items = self._fill_tree(classifier, set(species))
        self._update_counts()
        # Ticking a family changes all its species, each signalling, so the counts are updated once after
        self._counts_timer = QTimer(self, singleShot=True, interval=0)
        self._counts_timer.timeout.connect(self._update_counts)
        self.ui.species_tree.itemChanged.connect(self._counts_timer.start)

        # Not on ticking, so a species unticked with Show selected only stays put under the mouse
        self.ui.search_line_edit.textChanged.connect(self._filter)
        self.ui.selected_only_check_box.toggled.connect(self._filter)
        self.ui.clear_button.clicked.connect(self._clear)

    def species(self) -> list[str]:
        """The ticked species in the model's Genus_species form, in tree order."""
        return [item.data(0, SPECIES_ROLE) for item in self._species_items
                if item.checkState(0) == Qt.CheckState.Checked]

    def _fill_tree(self, classifier: Classifier, ticked: set[str]) -> list[QTreeWidgetItem]:
        """Adds the families, genera and species sorted by name. Returns the species items."""
        tree: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for name, genus, family in zip(classifier.species, classifier.genus_of, classifier.family_of, strict=True):
            tree[classifier.families[family]][classifier.genera[genus]].append(name)

        def checkable(parent, name: str, tristate: bool) -> QTreeWidgetItem:
            item = QTreeWidgetItem(parent, [name])
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags | Qt.ItemFlag.ItemIsAutoTristate if tristate else flags)
            # Set before the children are added, as setting a parent's state sets theirs
            item.setCheckState(0, Qt.CheckState.Unchecked)
            return item

        species_items = []
        for family in sorted(tree):
            family_item = checkable(self.ui.species_tree, family, tristate=True)
            family_item.setData(0, NAME_ROLE, family)
            for genus in sorted(tree[family]):
                genus_item = checkable(family_item, genus, tristate=True)
                genus_item.setData(0, NAME_ROLE, genus)
                for name in sorted(tree[family][genus]):
                    item = checkable(genus_item, display_name(name), tristate=False)
                    item.setData(0, SPECIES_ROLE, name)
                    item.setData(0, SEARCH_ROLE, f"{family} {genus} {display_name(name)}".lower())
                    if name in ticked:
                        item.setCheckState(0, Qt.CheckState.Checked)
                    species_items.append(item)
        return species_items

    def _update_counts(self):
        """Shows "(ticked/total)" after each family and genus, and the ticked species of all below the tree."""
        ticked_total = 0
        # Blocked, as each new text would signal itemChanged and start another update
        with QSignalBlocker(self.ui.species_tree):
            for family in _children(self.ui.species_tree.invisibleRootItem()):
                family_ticked = family_total = 0
                for genus in _children(family):
                    ticked = sum(item.checkState(0) == Qt.CheckState.Checked for item in _children(genus))
                    genus.setText(0, f"{genus.data(0, NAME_ROLE)} ({ticked}/{genus.childCount()})")
                    family_ticked += ticked
                    family_total += genus.childCount()
                family.setText(0, f"{family.data(0, NAME_ROLE)} ({family_ticked}/{family_total})")
                ticked_total += family_ticked
        self.ui.count_label.setText(f"{ticked_total} of {len(self._species_items)} species")

    def _filter(self):
        """
        Shows the species matching the search, only the ticked ones with Show
        selected only, and the families and genera holding any of them.
        Filtering expands what it shows, except fully ticked genera with Show
        selected only, which would repeat a whole genus.
        """
        needle = self.ui.search_line_edit.text().strip().lower()
        selected_only = self.ui.selected_only_check_box.isChecked()
        for family in _children(self.ui.species_tree.invisibleRootItem()):
            family_shown = False
            for genus in _children(family):
                genus_shown = False
                for item in _children(genus):
                    shown = ((not selected_only or item.checkState(0) == Qt.CheckState.Checked)
                             and needle in item.data(0, SEARCH_ROLE))
                    item.setHidden(not shown)
                    genus_shown |= shown
                genus.setHidden(not genus_shown)
                genus.setExpanded(bool(needle) or (selected_only and genus.checkState(0) == Qt.CheckState.PartiallyChecked))
                family_shown |= genus_shown
            family.setHidden(not family_shown)
            family.setExpanded(bool(needle) or selected_only)

    def _clear(self):
        for family in _children(self.ui.species_tree.invisibleRootItem()):
            family.setCheckState(0, Qt.CheckState.Unchecked)
