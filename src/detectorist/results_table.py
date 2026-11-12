from collections.abc import Set

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem

from .classifier import display_name, identified_ranks
from .structures import RANK_COUNT

# The detector's class and score, a name and score per rank the classifier names, then the list fit
HEADER_LABELS = ["Detected", "Score", "Family", "Score", "Genus", "Score", "Species", "Score", "List fit"]
TAXONOMY_COLUMNS = range(2, 2 + 2 * RANK_COUNT)
LIST_FIT_COLUMN = TAXONOMY_COLUMNS.stop
SCORE_COLUMNS = (1, *TAXONOMY_COLUMNS[1::2], LIST_FIT_COLUMN)
# Where an item keeps its detection's box, in column 0
BOX_ROLE = Qt.ItemDataRole.UserRole
# Where an item keeps a score cell's unrounded score, which sorting compares
SCORE_ROLE = Qt.ItemDataRole.UserRole + 1


class _ResultItem(QTreeWidgetItem):
    """
    A row that sorts score columns by the unrounded score. Their text caps
    at 0.99, so two species shown as 0.99 would tie and keep the detection
    order, while the best classification crop frames the higher score.
    """

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        column = self.treeWidget().sortColumn()
        score, other_score = self.data(column, SCORE_ROLE), other.data(column, SCORE_ROLE)
        # Not super().__lt__, which PySide routes back into this override
        if score is None or other_score is None:
            return self.text(column) < other.text(column)
        return score < other_score


def format_score(score: float) -> str:
    """
    A score with two decimals, capped at 0.99. Rounding would show 1.00 for
    0.995 and up, which a family or genus often reaches as the sum of its
    species' probabilities, and no score means certainty.
    """
    return f"{min(score, 0.99):.2f}"


def _set_score(item: QTreeWidgetItem, column: int, score: float) -> None:
    """Shows a score right-aligned in column, keeping it unrounded for sorting."""
    item.setText(column, format_score(score))
    item.setData(column, SCORE_ROLE, score)
    item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class ResultsTable(QTreeWidget):
    """
    Lists the shown image's detections, one row each, with what the classifier
    named them. Hovering a row tints it and reports its detection's box, and
    the row of a box set with set_highlighted_box is tinted too.
    """

    # The box of the detection whose row is under the mouse, or None
    row_hovered = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(HEADER_LABELS)
        self.headerItem().setToolTip(LIST_FIT_COLUMN, "Share of the model's confidence that fell on the listed "
                                     "species. Low values suggest a species not on the list")
        # The scores fit their header, the names share the rest of the width
        header = self.header()
        header.setStretchLastSection(False)
        for column in range(len(HEADER_LABELS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents if column in SCORE_COLUMNS
                                        else QHeaderView.ResizeMode.Stretch)
        self.setSortingEnabled(True)
        # Unsorted until the user clicks a column header, so the rows keep the highest score first
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.set_list_fit_visible(False)
        # Where the mouse last was over the viewport, or None, as rows can change under a resting mouse
        self._mouse_pos: QPoint | None = None
        self._hovered_box = None
        self._highlighted_box = None
        self.viewport().setMouseTracking(True)

    def show_detections(self, detections: list, taxonomy_by_box: dict, threshold: float, pending: Set = frozenset()):
        """
        Lists the detections, the highest score first unless the user sorted by
        a column. A classified detection's row goes down to the deepest rank at
        or above threshold, or says "Unidentified" if there is none. One whose
        box is in pending, still to be named, says "..." in place of its name.
        The list fit column is filled for a detection named from a species list.
        """
        # Kept, as the rows are rebuilt on every slider move and classification
        scroll_position = self.verticalScrollBar().value()
        super().clear()
        for detection in sorted(detections, key=lambda d: d.score, reverse=True):
            item = _ResultItem([detection.class_name])
            item.setData(0, BOX_ROLE, detection.box)
            _set_score(item, SCORE_COLUMNS[0], detection.score)
            if (taxonomy := taxonomy_by_box.get(detection.box)) is not None:
                ranks = identified_ranks(taxonomy, threshold)
                for column, rank in zip(TAXONOMY_COLUMNS[::2], ranks, strict=False):  # ranks stop at the threshold
                    item.setText(column, display_name(rank.name))
                    _set_score(item, column + 1, rank.score)
                if not ranks:
                    item.setText(TAXONOMY_COLUMNS.start, "Unidentified")
                if taxonomy.list_fit is not None:
                    _set_score(item, LIST_FIT_COLUMN, taxonomy.list_fit)
            elif detection.box in pending:
                item.setText(TAXONOMY_COLUMNS.start, "...")
            self._set_highlighted(item, detection.box == self._highlighted_box)
            self.addTopLevelItem(item)
        self.verticalScrollBar().setValue(scroll_position)
        self._update_hovered_box()

    def clear(self):
        super().clear()
        self._update_hovered_box()

    def set_taxonomy_visible(self, visible: bool):
        """Shows or hides the columns of the names the classifier gives."""
        for column in TAXONOMY_COLUMNS:
            self.setColumnHidden(column, not visible)

    def set_list_fit_visible(self, visible: bool):
        """Shows or hides the list fit column, which only a species list fills."""
        self.setColumnHidden(LIST_FIT_COLUMN, not visible)

    def set_highlighted_box(self, box):
        """
        Tints the row of the detection with the given box, or none for None. The table is not scrolled to it, as moving the mouse over the
        image would keep scrolling the table.
        """
        self._highlighted_box = box
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            self._set_highlighted(item, item.data(0, BOX_ROLE) == box)

    def _set_highlighted(self, item: QTreeWidgetItem, highlighted: bool):
        # A tint rather than bold, as bold text is wider and would resize the score columns.
        # Fainter than the selection, so a hovered row still shows whether it is selected.
        brush = None
        if highlighted:
            color = self.palette().color(QPalette.ColorRole.Highlight)
            color.setAlphaF(0.3)
            brush = color
        for column in range(self.columnCount()):
            item.setData(column, Qt.ItemDataRole.BackgroundRole, brush)

    def viewportEvent(self, event):
        # The rows are drawn on the viewport, so it gets the mouse, and the table has no signal for leaving a row
        if event.type() == QEvent.Type.MouseMove:
            self._mouse_pos = event.position().toPoint()
            self._update_hovered_box()
        elif event.type() == QEvent.Type.Leave:
            self._mouse_pos = None
            self._update_hovered_box()
        return super().viewportEvent(event)

    def _update_hovered_box(self):
        """Reports the box of the row under the mouse. Called after the rows change too."""
        item = None if self._mouse_pos is None else self.itemAt(self._mouse_pos)
        box = None if item is None else item.data(0, BOX_ROLE)
        if box != self._hovered_box:
            self._hovered_box = box
            self.set_highlighted_box(box)
            self.row_hovered.emit(box)
