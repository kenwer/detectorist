"""Smoke tests for the About and Shortcuts dialogs.

Both render Markdown from the compiled Qt resources, so a broken resource
path or .ui change shows up here as an empty dialog or an exception.
"""

from PySide6.QtWidgets import QDialog, QLabel, QTextBrowser

from detectorist import __version__
from detectorist.about_dialog import show_about_dialog
from detectorist.shortcuts_dialog import ShortcutsDialog


def test_shortcuts_dialog_renders_the_shortcuts_document(qtbot):
    dialog = ShortcutsDialog()
    qtbot.addWidget(dialog)

    assert dialog.ui.shortcuts_text_browser.toPlainText().strip()


def test_about_dialog_shows_version_changelog_and_acknowledgements(qtbot, monkeypatch):
    shown = []
    # exec() would block on a modal dialog, so capture the dialog instead
    monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(self))

    show_about_dialog()

    (dialog,) = shown
    qtbot.addWidget(dialog)
    assert dialog.findChild(QLabel, "version_label").text() == f"Version: {__version__}"
    assert dialog.findChild(QTextBrowser, "changelog_text_browser").toPlainText().strip()
    assert "RF-DETR" in dialog.findChild(QTextBrowser, "acknowledgements_text_browser").toPlainText()
