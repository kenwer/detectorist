"""Tests for the toast link, the one part of the toast helpers with logic of its own.

pyqttoast has no rich text API, so the link reaches into a private label of
Toast, the reason the dependency is pinned in pyproject.toml. The autouse
toasts fixture replaces _show_toast with a recorder, so the real function is
imported before that happens.
"""

from pyqttoast import Toast, ToastPreset
from PySide6.QtWidgets import QWidget

from detectorist.toasts import _show_toast as real_show_toast


def test_a_toast_link_runs_its_callback(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    # A shown toast starts pyqttoast's class-level queue and timers, which outlive the test
    monkeypatch.setattr(Toast, "show", lambda self: None)
    clicked = []

    toast = real_show_toast(parent, "Done", "Exported.", ToastPreset.SUCCESS, link_text="Reveal",
                            on_link=lambda: clicked.append(True))

    label = toast._Toast__text_label
    assert '<a href="#">Reveal</a>' in label.text()
    label.linkActivated.emit("#")
    assert clicked == [True]
