"""A QButtonGroup read and set as an enum value."""

from collections.abc import Mapping
from enum import Enum

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QAbstractButton, QButtonGroup


class EnumButtonGroup[E: Enum](QObject):
    """
    The buttons of an exclusive QButtonGroup, each standing for one enum value,
    so callers read and set the value rather than look for the checked button.
    """

    value_changed = Signal(object)  # the new value, once per change, including changes by set_value()

    def __init__(self, group: QButtonGroup, buttons: Mapping[E, QAbstractButton]):
        # Parented to the group, so it lives as long as the buttons it reads
        super().__init__(group)
        self._group = group
        self._values = list(buttons)
        for button_id, button in enumerate(buttons.values()):
            group.setId(button, button_id)
        group.idToggled.connect(self._on_id_toggled)

    def value(self) -> E | None:
        """The value of the checked button, or None while none is checked."""
        button_id = self._group.checkedId()
        return self._values[button_id] if button_id >= 0 else None

    def set_value(self, value: E) -> None:
        self.button(value).setChecked(True)

    def button(self, value: E) -> QAbstractButton:
        return self._group.button(self._values.index(value))

    @Slot(int, bool)
    def _on_id_toggled(self, button_id: int, checked: bool) -> None:
        # A change unchecks one button and checks another, so only the second counts
        if checked:
            self.value_changed.emit(self._values[button_id])
