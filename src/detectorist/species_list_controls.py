"""The species list controls next to the classifier choice."""

from collections.abc import Callable

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QDialog, QPushButton, QWidget

from .classifier import display_name
from .pipeline import Pipeline
from .species_list_dialog import SpeciesListDialog
from .species_lists import SpeciesLists
from .toasts import show_warning_toast

# Unknown species named in the toast before the rest are only counted
UNKNOWN_SHOWN = 5


class SpeciesListControls(QObject):
    """
    The check box that switches the chosen classifier's species list on and
    off, and the button that summarises the list and edits it in the Species
    List dialog. Keeps the Pipeline restricted to the list of the chosen
    classifier.
    """

    def __init__(self, button: QPushButton, check_box: QCheckBox, pipeline: Pipeline, lists: SpeciesLists,
                 classifier_name: Callable[[str], str], window: QWidget):
        """
        Args:
            classifier_name: The name a classifier's model file is shown by.
            window: Parent of the dialog and the toasts.
        """
        super().__init__(window)
        self._button = button
        self._check_box = check_box
        self._pipeline = pipeline
        self._lists = lists
        self._classifier_name = classifier_name
        self._window = window
        # The model file of the classifier chosen last, which pipeline.classifier is once loaded, or None
        self._filename: str | None = None
        pipeline.classifier_loaded.connect(self.apply)
        button.clicked.connect(self._edit)
        check_box.toggled.connect(self._on_toggled)

    def classifier_chosen(self, filename: str | None) -> None:
        """
        Restricts a classifier the Pipeline has started to load to its list,
        taking over that of a model it supersedes, or to none for None.
        """
        if filename:
            self._lists.adopt_superseded(filename)
        self._filename = filename
        self.apply()

    def apply(self) -> None:
        """
        Restricts the chosen classifier to its species list, or to none while
        the list is switched off. Once it has loaded, species it does not know
        are removed from the list, and the user is told which.
        """
        classifier = self._pipeline.classifier
        if classifier is not None and (unknown := self._lists.fit_to(self._filename, classifier.species)):
            self._report_unknown(unknown)
        self._pipeline.set_species(self._lists.applied(self._filename) if self._filename else [])
        self._show()

    def _show(self) -> None:
        """Summarises the list on the button and shows whether it is on. Both can be changed once loaded."""
        loaded = self._pipeline.classifier is not None
        species = self._lists.get(self._filename) if self._filename else []
        on = bool(species) and self._lists.is_on(self._filename)
        self._button.setText(f"{len(species)} species" if on else "All (list off)" if species else "All")
        self._button.setEnabled(loaded)
        with QSignalBlocker(self._check_box):
            self._check_box.setChecked(on)
        self._check_box.setEnabled(loaded and bool(species))

    def _on_toggled(self, on: bool) -> None:
        self._lists.set_on(self._filename, on)
        self.apply()

    def _edit(self) -> None:
        """Lets the user pick the species the loaded classifier names, in the Species List dialog."""
        classifier = self._pipeline.classifier
        dialog = SpeciesListDialog(self._classifier_name(self._filename), classifier,
                                   self._lists.get(self._filename), self._window)
        # A finished download may have loaded another classifier meanwhile, which the list was not picked for
        if dialog.exec() != QDialog.DialogCode.Accepted or self._pipeline.classifier is not classifier:
            return
        # Switched on, as editing a list that was switched off means using it
        self._lists.set(self._filename, dialog.species(), on=True)
        self.apply()

    def _report_unknown(self, unknown: list[str]) -> None:
        names = ", ".join(display_name(name) for name in unknown[:UNKNOWN_SHOWN])
        if len(unknown) > UNKNOWN_SHOWN:
            names += f" and {len(unknown) - UNKNOWN_SHOWN} more"
        text = (f"{self._classifier_name(self._filename)} does not know {names}. "
                f"{'It was' if len(unknown) == 1 else 'They were'} removed from its species list.")
        if not self._lists.get(self._filename):
            text += " The list is now empty, so the classifier names any species."
        show_warning_toast(self._window, "Species list changed", text)
