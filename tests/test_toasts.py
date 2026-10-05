"""Tests for the toast helpers.

The autouse toasts fixture replaces _show_toast with a recorder, so these
check what each public helper forwards. One test builds a real pyqttoast
Toast (without showing it) to check the private label the link feature
depends on, which is the reason the dependency is pinned in pyproject.toml.
"""

from pyqttoast import Toast
from PySide6.QtWidgets import QLabel, QWidget

from detectorist.toasts import show_error_toast, show_success_toast, show_warning_toast


def test_success_toast_forwards_the_link(toasts):
    def on_link():
        pass

    show_success_toast(None, "Done", "Exported.", link_text="Show", on_link=on_link)

    assert toasts == [("success", "Done", "Exported.", {"link_text": "Show", "on_link": on_link, "duration": None})]


def test_error_toast(toasts):
    show_error_toast(None, "Failed", "No such file.")

    assert toasts == [("error", "Failed", "No such file.", {"duration": None})]


def test_warning_toast_forwards_the_duration(toasts):
    show_warning_toast(None, "Careful", "Folder missing.", duration=0)

    assert toasts == [("warning", "Careful", "Folder missing.", {"duration": 0})]


def test_pyqttoast_still_has_the_text_label_the_link_needs(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)

    toast = Toast(parent)

    assert isinstance(getattr(toast, "_Toast__text_label", None), QLabel)
