import os

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QColor

_DEFAULT_PARENT = QModelIndex()
_CACHED_TEXT_COLOR = QColor("darkgreen")  # SVG darkgreen (0,100,0); no Qt.GlobalColor goes this dark

class ImageListModel(QAbstractListModel):
    """
    A custom QAbstractListModel to manage a list of image file paths.
    It stores the full paths to the images but displays only the filenames.
    A custom role `FullPathRole` is provided to retrieve the full path.
    """
    FullPathRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_paths = []
        self._cached_paths: frozenset[str] = frozenset()

    def rowCount(self, parent=_DEFAULT_PARENT):
        """Returns the number of images in the model."""
        if parent.isValid():
            return 0
        return len(self._image_paths)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Returns the data for a given index and role."""
        if not index.isValid() or not (0 <= index.row() < len(self._image_paths)):
            return None

        path = self._image_paths[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return os.path.basename(path)
        elif role == self.FullPathRole:
            return path
        elif role == Qt.ItemDataRole.ForegroundRole and path in self._cached_paths:
            return _CACHED_TEXT_COLOR
        return None

    def setImagePaths(self, paths: list[str]):
        """Sets the list of image paths, replacing the existing ones."""
        self.beginResetModel()
        self._image_paths = paths
        # A fresh row set makes any leftover highlighting meaningless; the
        # worker's own clear_cache signal will confirm this shortly after,
        # but resetting here avoids depending on that queued signal's timing.
        self._cached_paths = frozenset()
        self.endResetModel()

    def removeImagePaths(self, indices: list[int]):
        """Removes items (paths of images) from the model based on the provided list of indices."""
        if not indices:
            return
        if len(indices) == 1:
            index_row = indices[0]
            if 0 <= index_row < len(self._image_paths):
                self.beginRemoveRows(_DEFAULT_PARENT, index_row, index_row)
                del self._image_paths[index_row]
                self.endRemoveRows()
        else:
            # Bulk removal: single reset is O(1) vs O(n) individual row signals
            index_set = set(indices)
            self.beginResetModel()
            self._image_paths = [p for i, p in enumerate(self._image_paths) if i not in index_set]
            self.endResetModel()

    def clear(self):
        """Clears all image paths from the model."""
        self.setImagePaths([])

    def setCachedPaths(self, paths: list[str]):
        """
        Updates which paths are highlighted as already analyzed (served
        instantly from the worker's cache). Connected to the worker's
        cache_updated signal, which arrives on the GUI thread via a queued
        connection.
        """
        cached_paths = frozenset(paths)
        if cached_paths == self._cached_paths:
            return
        self._cached_paths = cached_paths
        if self._image_paths:
            self.dataChanged.emit(
                self.index(0), self.index(len(self._image_paths) - 1),
                [Qt.ItemDataRole.ForegroundRole],
            )

    def imagePaths(self) -> list[str]:
        """Returns the list of all full image paths."""
        return self._image_paths
