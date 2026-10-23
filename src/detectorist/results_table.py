from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem

from .classifier import display_name, identified_ranks

# The detector's class and score, then a name and score per rank the classifier names
HEADER_LABELS = ["Detected", "Score", "Family", "Score", "Genus", "Score", "Species", "Score"]
TAXONOMY_COLUMNS_START = 2
# Where an item keeps its detection's box, in column 0
BOX_ROLE = Qt.ItemDataRole.UserRole


def _is_score_column(column: int) -> bool:
    return column % 2 == 1


class ResultsTable(QTreeWidget):
    """
    Lists the shown image's detections, one row each, with what the classifier
    named them. Hovering a row shows it in bold and reports its detection's
    box, and the row of a box set with set_bold_box is shown in bold too.
    """

    # The box of the detection whose row is under the mouse, or None
    row_hovered = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(HEADER_LABELS)
        # The scores fit their header, the names share the rest of the width
        header = self.header()
        header.setStretchLastSection(False)
        for column in range(len(HEADER_LABELS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents if _is_score_column(column)
                                        else QHeaderView.ResizeMode.Stretch)
        self.setSortingEnabled(True)
        # Unsorted until the user clicks a column header, so the rows keep the highest score first
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        # Where the mouse last was over the viewport, or None, as rows can change under a resting mouse
        self._mouse_pos: QPoint | None = None
        self._hovered_box = None
        self._bold_box = None
        self.viewport().setMouseTracking(True)

    def show_detections(self, detections: list, taxonomy_by_box: dict, threshold: float):
        """
        Lists the detections, the highest score first unless the user sorted by
        a column. A classified detection's row goes down to the deepest rank at
        or above threshold, or says "Unidentified" if there is none.
        """
        # Kept, as the rows are rebuilt on every slider move and classification
        scroll_position = self.verticalScrollBar().value()
        super().clear()
        for detection in sorted(detections, key=lambda d: d.score, reverse=True):
            cells = [detection.class_name, f"{detection.score:.2f}"]
            if (taxonomy := taxonomy_by_box.get(detection.box)) is not None:
                ranks = identified_ranks(taxonomy, threshold)
                for rank in ranks:
                    cells += [display_name(rank.name), f"{rank.score:.2f}"]
                if not ranks:
                    cells.append("Unidentified")
            item = QTreeWidgetItem(cells)
            item.setData(0, BOX_ROLE, detection.box)
            for column in filter(_is_score_column, range(len(cells))):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._set_bold(item, detection.box == self._bold_box)
            self.addTopLevelItem(item)
        self.verticalScrollBar().setValue(scroll_position)
        self._update_hovered_box()

    def clear(self):
        super().clear()
        self._update_hovered_box()

    def set_taxonomy_visible(self, visible: bool):
        """Shows or hides the columns of the names the classifier gives."""
        for column in range(TAXONOMY_COLUMNS_START, self.columnCount()):
            self.setColumnHidden(column, not visible)

    def set_bold_box(self, box):
        """
        Shows the row of the detection with the given box in bold, or none for
        None. The table is not scrolled to it, as moving the mouse over the
        image would keep scrolling the table.
        """
        self._bold_box = box
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            self._set_bold(item, item.data(0, BOX_ROLE) == box)

    def _set_bold(self, item: QTreeWidgetItem, bold: bool):
        font = item.font(0)
        font.setBold(bold)
        for column in range(self.columnCount()):
            item.setFont(column, font)

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
            self.set_bold_box(box)
            self.row_hovered.emit(box)
