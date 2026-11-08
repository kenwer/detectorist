"""Offers an available update, with its release notes."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout, QWidget

from .feed import Update


class UpdateDialog(QDialog):
    """Accepted means install, or with a block_reason open the download page.

    With a block_reason the app cannot install by itself, so the dialog
    explains why and offers the download page instead.
    """

    def __init__(
        self, update: Update, current_version: str, block_reason: str | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update available")
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Current version: {current_version}\nNew version: {update.version}"))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(update.notes or "No release notes.")
        layout.addWidget(notes)
        if block_reason:
            reason = QLabel(block_reason)
            reason.setWordWrap(True)
            layout.addWidget(reason)

        buttons = QDialogButtonBox()
        primary_text = "Open download page" if block_reason else "Download and install"
        primary = buttons.addButton(primary_text, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        primary.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
