"""Non-modal toast notifications for short-running actions.

Wraps pyqt-toast-notification so callers get a one-line helper and the
version-specific link handling stays in a single place.
"""

from collections.abc import Callable

from pyqttoast import Toast, ToastPreset
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget


def _show_toast(
    parent: QWidget,
    title: str,
    text: str,
    preset: ToastPreset,
    *,
    link_text: str | None = None,
    on_link: Callable[[], None] | None = None,
    duration: int | None = None,
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
        toast.setText(text)

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
    )


def show_error_toast(
    parent: QWidget,
    title: str,
    text: str,
    *,
    duration: int | None = None,
) -> Toast:
    """Show a non-blocking error toast."""
    return _show_toast(parent, title, text, ToastPreset.ERROR, duration=duration)


def show_warning_toast(
    parent: QWidget,
    title: str,
    text: str,
    *,
    duration: int | None = None,
) -> Toast:
    """Show a non-blocking warning toast."""
    return _show_toast(parent, title, text, ToastPreset.WARNING, duration=duration)
