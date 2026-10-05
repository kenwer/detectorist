"""Tests for ImageListModel, the list model behind the image list view.

The model shows basenames, hands out full paths through FullPathRole, and
colours the rows the worker already has cached.
"""

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor

from detectorist.image_list_model import ImageListModel

PATHS = ["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"]


@pytest.fixture
def model(qapp):
    model = ImageListModel()
    model.setImagePaths(list(PATHS))
    return model


def displayed(model):
    return [model.data(model.index(row)) for row in range(model.rowCount())]


def test_rows_show_basenames_and_expose_full_paths(model):
    assert model.rowCount() == 3
    assert displayed(model) == ["a.jpg", "b.jpg", "c.jpg"]
    assert model.data(model.index(1), ImageListModel.FullPathRole) == "/photos/b.jpg"
    assert model.imagePaths() == PATHS


def test_invalid_index_has_no_data(model):
    assert model.data(QModelIndex()) is None
    # A list has no child rows
    assert model.rowCount(model.index(0)) == 0


def test_removing_one_row_emits_rows_removed(qtbot, model):
    with qtbot.waitSignal(model.rowsRemoved):
        model.removeImagePaths([1])

    assert displayed(model) == ["a.jpg", "c.jpg"]


def test_removing_several_rows_resets_the_model(qtbot, model):
    with qtbot.waitSignal(model.modelReset):
        model.removeImagePaths([0, 2])

    assert displayed(model) == ["b.jpg"]


def test_removing_nothing_or_an_unknown_row_changes_nothing(qtbot, model):
    with qtbot.assertNotEmitted(model.rowsRemoved), qtbot.assertNotEmitted(model.modelReset):
        model.removeImagePaths([])
        model.removeImagePaths([7])

    assert displayed(model) == ["a.jpg", "b.jpg", "c.jpg"]


def test_clear_empties_the_model(model):
    model.clear()
    assert model.rowCount() == 0


def test_cached_paths_are_highlighted(qtbot, model):
    with qtbot.waitSignal(model.dataChanged):
        model.setCachedPaths(["/photos/b.jpg"])

    assert isinstance(model.data(model.index(1), Qt.ItemDataRole.ForegroundRole), QColor)
    assert model.data(model.index(0), Qt.ItemDataRole.ForegroundRole) is None


def test_unchanged_cached_paths_emit_nothing(qtbot, model):
    model.setCachedPaths(["/photos/b.jpg"])

    with qtbot.assertNotEmitted(model.dataChanged):
        model.setCachedPaths(["/photos/b.jpg"])


def test_new_image_paths_drop_the_highlighting(model):
    model.setCachedPaths(["/photos/b.jpg"])

    model.setImagePaths(list(PATHS))

    assert model.data(model.index(1), Qt.ItemDataRole.ForegroundRole) is None
