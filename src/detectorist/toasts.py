# Not strict: pyqttoast has no type stubs
# pyright: standard
"""Non-modal toast notifications for short-running actions.

Wraps pyqt-toast-notification so callers get a one-line helper and the
version-specific link handling stays in a single place.
"""

import math
from collections.abc import Callable

from pyqttoast import Toast, ToastPreset
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QTextDocument
from PySide6.QtWidgets import QApplication, QWidget


def _fit_width_to_markdown(toast: Toast) -> None:
    """
    Caps the toast width at what its Markdown text needs, so pyqttoast sizes
    the text label by its size hint. Otherwise pyqttoast measures the raw
    Markdown as a single line, so the toast is as wide as all of it and one
    line high.
    """
    document = QTextDocument()
    document.setDefaultFont(toast.getTextFont())
    document.setDocumentMargin(0)
    document.setMarkdown(toast.getText())
    content = max(math.ceil(document.idealWidth()),
                  QFontMetrics(toast.getTitleFont()).horizontalAdvance(toast.getTitle()))
    margins, icon_margins = toast.getMargins(), toast.getIconMargins()
    icon_section, text_section = toast.getIconSectionMargins(), toast.getTextSectionMargins()
    close_margins = toast.getCloseButtonMargins()
    icon = (icon_section.left() + icon_margins.left() + toast.getIconSize().width() + icon_margins.right()
            + toast.getIconSeparatorWidth() + icon_section.right()) if toast.isShowIcon() else 0
    close = (close_margins.left() + toast.getCloseButtonWidth()
             + close_margins.right()) if toast.isShowCloseButton() else 0
    toast.setMaximumWidth(margins.left() + icon + text_section.left() + content + text_section.right()
                          + close + margins.right())


def _show_toast(
    parent: QWidget,
    title: str,
    text: str,
    preset: ToastPreset,
    *,
    link_text: str | None = None,
    on_link: Callable[[], None] | None = None,
    duration: int | None = None,
    markdown: bool = False,
) -> Toast:
    """Build and show a toast with the given preset.

    The default toast position is bottom-right (pyqttoast's own default), so it
    does not steal focus from the main window.

    When link_text and on_link are given, the text label is switched to rich
    text and a trailing link is appended. Clicking it invokes on_link. pyqttoast
    1.3.3 has no public rich-text API, so the internal text label is accessed via
    its name-mangled attribute; if a future version renames it, the toast falls
    back to plain text instead of raising.

    Args:
        parent: Widget the toast is parented to.
        title: Bold title line.
        text: Body text.
        preset: pyqttoast style preset (success, error, warning, ...).
        link_text: Visible text of the trailing link, or None for no link.
        on_link: Callback invoked when the link is clicked.
        duration: Auto-dismiss time in milliseconds. None keeps pyqttoast's
            default (5000); 0 disables auto-dismiss.
        markdown: Whether text is Markdown, shown formatted and selectable
            so it can be copied. Ignored when a link is given. Like the link, it
            goes through the internal text label, and shows as plain text if
            that label is renamed.

    Returns:
        The shown Toast instance.
    """
    toast = Toast(parent)
    if duration is not None:
        toast.setDuration(duration)
    toast.setTitle(title)
    toast.applyPreset(preset)

    # pyqttoast defaults to Arial 9pt, which is small and non-native. Use the app
    # font family so the toast matches the UI, with a floor so it stays legible
    # regardless of the platform default point size.
    base_font = QApplication.font()
    text_size = max(base_font.pointSize(), 13)
    text_font = QFont(base_font)
    text_font.setPointSize(text_size)
    toast.setTextFont(text_font)
    title_font = QFont(base_font)
    title_font.setPointSize(text_size + 1)
    title_font.setBold(True)
    toast.setTitleFont(title_font)

    label = getattr(toast, "_Toast__text_label", None)
    if link_text and on_link is not None and label is not None:
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        # Keep openExternalLinks off so the click reaches us via linkActivated
        # instead of the label trying to open the placeholder href itself.
        label.linkActivated.connect(lambda _href: on_link())
        toast.setText(f'{text} <a href="#">{link_text}</a>')
    else:
        # Set before show(), as pyqttoast sizes the toast to its text there
        if markdown and label is not None:
            label.setTextFormat(Qt.TextFormat.MarkdownText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        toast.setText(text)
        if markdown and label is not None:
            _fit_width_to_markdown(toast)

    toast.show()
    return toast


def show_success_toast(
    parent: QWidget,
    title: str,
    text: str,
    *,
    link_text: str | None = None,
    on_link: Callable[[], None] | None = None,
    duration: int | None = None,
    markdown: bool = False,
) -> Toast:
    """Show a success toast, optionally ending in a clickable link."""
    return _show_toast(
        parent,
        title,
        text,
        ToastPreset.SUCCESS,
        link_text=link_text,
        on_link=on_link,
        duration=duration,
        markdown=markdown,
    )


def show_info_toast(
    parent: QWidget,
    title: str,
    text: str,
    *,
    link_text: str | None = None,
    on_link: Callable[[], None] | None = None,
    duration: int | None = None,
    markdown: bool = False,
) -> Toast:
    """Show a non-blocking information toast, optionally ending in a clickable link."""
    return _show_toast(
        parent,
        title,
        text,
        ToastPreset.INFORMATION,
        link_text=link_text,
        on_link=on_link,
        duration=duration,
        markdown=markdown,
    )


def show_error_toast(
    parent: QWidget,
    title: str,
    text: str,
    *,
    duration: int | None = None,
    markdown: bool = False,
) -> Toast:
    """Show a non-blocking error toast."""
    return _show_toast(parent, title, text, ToastPreset.ERROR, duration=duration, markdown=markdown)


def show_warning_toast(
    parent: QWidget,
    title: str,
    text: str,
    *,
    link_text: str | None = None,
    on_link: Callable[[], None] | None = None,
    duration: int | None = None,
    markdown: bool = False,
) -> Toast:
    """Show a non-blocking warning toast, optionally ending in a clickable link."""
    return _show_toast(
        parent,
        title,
        text,
        ToastPreset.WARNING,
        link_text=link_text,
        on_link=on_link,
        duration=duration,
        markdown=markdown,
    )
