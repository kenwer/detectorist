"""Tests for the toast link and Markdown text, the parts of the toast helpers with logic of their own.

pyqttoast has no rich text API, so both reach into a private label of
Toast, the reason the dependency is pinned in pyproject.toml. The autouse
toasts fixture replaces _show_toast with a recorder, so the real function is
imported before that happens.
"""

from pyqttoast import Toast, ToastPreset
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from detectorist.toasts import _show_toast as real_show_toast
from tests.fakes import of_type


def test_a_toast_link_runs_its_callback(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    # A shown toast starts pyqttoast's class-level queue and timers, which outlive the test
    monkeypatch.setattr(Toast, "show", lambda self: None)
    clicked = []

    toast = real_show_toast(parent, "Done", "Exported.", ToastPreset.SUCCESS, link_text="Reveal",
                            on_link=lambda: clicked.append(True))

    label = of_type(getattr(toast, "_Toast__text_label", None), QLabel)
    assert '<a href="#">Reveal</a>' in label.text()
    label.linkActivated.emit("#")
    assert clicked == [True]


def test_a_markdown_toast_formats_its_text_and_lets_it_be_selected(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    monkeypatch.setattr(Toast, "show", lambda self: None)

    toast = real_show_toast(parent, "Imported", "Not found:\n\n- *Bombus terrestris*", ToastPreset.WARNING,
                            markdown=True)

    label = of_type(getattr(toast, "_Toast__text_label", None), QLabel)
    assert label.textFormat() == Qt.TextFormat.MarkdownText
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_a_markdown_toast_is_as_high_as_its_lines(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)

    toast = real_show_toast(parent, "Imported", "Not found:\n\n- *Bombus terrestris*\n- *Apis mellifera*",
                            ToastPreset.WARNING, duration=0, markdown=True)
    # Never dismissed by itself, so it would take one of the few places pyqttoast has on screen
    Toast.reset()

    label = of_type(getattr(toast, "_Toast__text_label", None), QLabel)
    assert label.height() == label.heightForWidth(label.width()) > 2 * label.fontMetrics().height()
