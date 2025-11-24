import os

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

_DEFAULT_PARENT = QModelIndex()

class ImageListModel(QAbstractListModel):
    """
    A custom QAbstractListModel to manage a list of image file paths.
    It stores the full paths to the images but displays only the filenames.
    A custom role `FullPathRole` is provided to retrieve the full path.
    """
    FullPathRole = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_paths = []

    def rowCount(self, parent=_DEFAULT_PARENT):
        """Returns the number of images in the model."""
        if parent.isValid():
            return 0
        return len(self._image_paths)

    def data(self, index, role=Qt.DisplayRole):
        """Returns the data for a given index and role."""
        if not index.isValid() or not (0 <= index.row() < len(self._image_paths)):
            return None

        path = self._image_paths[index.row()]

        if role == Qt.DisplayRole:
            return os.path.basename(path)
        elif role == self.FullPathRole:
            return path
        return None

    def setImagePaths(self, paths: list[str]):
        """Sets the list of image paths, replacing the existing ones."""
        self.beginResetModel()
        self._image_paths = paths
        self.endResetModel()

    def removeImagePaths(self, indices: list[int]):
        """Removes items (paths of images) from the model based on the provided list of indices."""
        # Sort indices in descending order to avoid issues with shifting indices
        for index_row in sorted(indices, reverse=True):
            if 0 <= index_row < len(self._image_paths):
                self.beginRemoveRows(_DEFAULT_PARENT, index_row, index_row)
                del self._image_paths[index_row]
                self.endRemoveRows()

    def clear(self):
        """Clears all image paths from the model."""
        self.setImagePaths([])

    def imagePaths(self) -> list[str]:
        """Returns the list of all full image paths."""
        return self._image_paths
