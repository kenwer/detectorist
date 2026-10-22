"""The Export dialog: which images to export, how to crop and name them, and where they go."""

import html
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace

from PySide6.QtCore import QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QWidget

from .export_planner import ExportOptions
from .structures import Box, Detection, Taxonomy
from .ui_export_dialog import Ui_ExportDialog
from .utils import contract_user_path, count_noun

OUTPUT_DIR_NAME = "processed"  # default export folder in the image folder


@dataclass(frozen=True)
class PreviewImage:
    """The one image whose detections are at hand, so the preview can name its files."""

    path: str
    detections: list[Detection]
    height: int
    width: int
    taxonomy_by_box: Mapping[Box, Taxonomy]

    def file_names(self, options: ExportOptions) -> list[str]:
        return [file.name for file in options.plan(os.path.basename(self.path), self.detections,
                                                   self.height, self.width, self.taxonomy_by_box)]


class ExportDialog(QDialog):
    """
    Asks which images to export, whether to crop them, what their names
    start with and where they go, and previews the files the export writes.
    """

    def __init__(self, all_images: list[str], selected_images: list[str], *,
                 options: ExportOptions, preview_image: PreviewImage | None, run_files: list[str],
                 crop_summary: str = "", class_filter: str | None = None, parent: QWidget | None = None):
        """
        Args:
            all_images: Full paths of the images in the list, all in one folder.
            selected_images: Full paths of the selected images, offered
                as the second choice after all images.
            options: The crop and prefix choices to start from. Without
                classifier patterns, the taxa prefix is unavailable, but
                stays chosen for the next export with a classifier.
            preview_image: The image the example names, while it is in scope.
                None, or out of scope, counts the images instead.
            run_files: The CSV and settings files the export writes alongside.
            crop_summary: The crop panel's settings, shown under the crop choice.
            class_filter: The class chosen in Show, which limits the export
                to its detections, or None for all classes.
        """
        super().__init__(parent)
        self.ui = Ui_ExportDialog()
        self.ui.setupUi(self)

        self._image_folder = os.path.dirname(all_images[0])
        self._all_images = all_images
        self._selected_images = selected_images
        self._preview_image = preview_image
        self._run_files = run_files
        self._options = options
        self._other_folder = ""

        self.ui.preview_label.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        self.ui.rb_all.setText(f"All images ({len(all_images)})")
        self.ui.rb_selected.setText(f"Selected images ({len(selected_images)})")
        self.ui.rb_selected.setEnabled(bool(selected_images))
        self.ui.class_filter_label.setText(f"Only {class_filter} detections (Show filter)" if class_filter else "")
        self.ui.class_filter_label.setVisible(bool(class_filter))

        self.ui.cb_crop.setChecked(options.crop)
        self.ui.crop_summary_label.setText(crop_summary)
        self.ui.crop_summary_label.setVisible(bool(crop_summary))
        self.ui.cb_prefix_class.setChecked(options.prefix_class)
        self.ui.cb_prefix_taxa.setChecked(options.prefix_taxa)
        if options.classifier_patterns is None:
            self.ui.cb_prefix_taxa.setEnabled(False)
            self.ui.cb_prefix_taxa.setText("Taxa (no classifier)")
            self.ui.cb_prefix_taxa.setToolTip("Select a classifier in the main window to name files by "
                                              "family, genus and species")

        # rb_selected toggles on every change between the two, rb_all would signal each change again
        self.ui.rb_selected.toggled.connect(self._update_preview)
        for check_box in (self.ui.cb_crop, self.ui.cb_prefix_class, self.ui.cb_prefix_taxa):
            check_box.toggled.connect(self._update_preview)
        self.ui.choose_button.clicked.connect(self._choose_folder)
        self.ui.default_link_label.linkActivated.connect(self._reset_folder)
        self.ui.output_path_label.linkActivated.connect(
            lambda _: QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir())))
        self.ui.output_path_label.installEventFilter(self)
        self._update_output_folder()
        # As tall as the preview's lines or the choices need, whichever is more
        self.resize(self.width(), self.minimumSizeHint().height())

    def images(self) -> list[str]:
        return self._selected_images if self.ui.rb_selected.isChecked() else self._all_images

    def options(self) -> ExportOptions:
        """The options given, with the crop and prefix chosen."""
        return replace(self._options, crop=self.ui.cb_crop.isChecked(), prefix_class=self.ui.cb_prefix_class.isChecked(),
                       prefix_taxa=self.ui.cb_prefix_taxa.isChecked())

    def output_dir(self) -> str:
        return self._other_folder or os.path.join(self._image_folder, OUTPUT_DIR_NAME)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export to Folder", self._other_folder or self._image_folder)
        if not folder:
            return
        self._other_folder = folder
        self._update_output_folder()

    def _reset_folder(self, _link: str = "") -> None:
        self._other_folder = ""
        self._update_output_folder()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # The path is elided to a width known only once the layout sizes the label
        if watched is self.ui.output_path_label and event.type() == QEvent.Type.Resize:
            self._show_output_path()
        return super().eventFilter(watched, event)

    def _show_output_path(self) -> None:
        """
        Shows the output folder elided to fit, as a link that opens it once
        it exists. A folder that does not exist yet has nothing to open.
        """
        label = self.ui.output_path_label
        path = contract_user_path(self.output_dir())
        elided = html.escape(label.fontMetrics().elidedText(path, Qt.TextElideMode.ElideMiddle, max(label.width(), 80)))
        if os.path.isdir(self.output_dir()):
            label.setText(f'<a href="open">{elided}</a>')
            label.setToolTip(path)
        else:
            label.setText(elided)
            label.setToolTip(f"{path}\nCreated when exporting")

    def _update_output_folder(self) -> None:
        """Shows the output folder and refuses the image folder itself, which would overwrite the originals."""
        in_image_folder = (os.path.normcase(os.path.realpath(self.output_dir()))
                           == os.path.normcase(os.path.realpath(self._image_folder)))
        self.ui.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not in_image_folder)
        self.ui.note_label.setText("Choose a folder other than the image folder, so the originals stay untouched."
                                   if in_image_folder else "Files already in the output folder with the same names are overwritten.")
        # Offered only once there is a default to go back to
        self.ui.default_link_label.setVisible(bool(self._other_folder))
        self._show_output_path()
        # The example names the output folder
        self._update_preview()

    def _update_preview(self) -> None:
        """Shows the naming scheme and an example of the files the export writes, and counts them on Export."""
        images = self.images()
        self.ui.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(f"Export {count_noun(len(images), 'Image')}")

        # The Output folder row shows the full path, so the example names only its last two folders
        parent, name = os.path.split(os.path.normpath(self.output_dir()))
        folder = f"{os.path.basename(parent)}/{name}/"
        more = [f"...and {len(images) - 1} more images"] if len(images) > 1 else []
        options = self.options()
        preview_image = self._preview_image
        names = preview_image.file_names(options) if preview_image and preview_image.path in images else None
        example = [count_noun(len(images), "image")] if names is None else names + more
        ext = os.path.splitext(names[0] if names else images[0])[1]
        scheme = [options.name_scheme(ext), *more]

        def block(label: str, top: str, entries: list[str]) -> str:
            lines = [top, *(f"    {entry}" for entry in entries + self._run_files)]
            return f"<b>{label}</b>\n" + "\n".join(html.escape(line) for line in lines)

        self.ui.preview_label.setText(f'<div style="white-space: pre">{block("Naming scheme:", "<output folder>", scheme)}'
                                      f'\n\n{block("Example:", folder, example)}</div>')
