from enum import Enum

import pytest
from PySide6.QtWidgets import QButtonGroup, QRadioButton, QWidget

from detectorist.enum_button_group import EnumButtonGroup


class Color(Enum):
    RED = "red"
    GREEN = "green"


@pytest.fixture
def parent(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def make_group(parent):
    buttons = {color: QRadioButton(color.value, parent) for color in Color}
    group = QButtonGroup(parent)
    for button in buttons.values():
        group.addButton(button)
    return EnumButtonGroup(group, buttons), buttons


def test_value_is_none_until_a_button_is_checked(parent):
    colors, _ = make_group(parent)

    assert colors.value() is None


def test_set_value_checks_its_button(parent):
    colors, buttons = make_group(parent)

    colors.set_value(Color.GREEN)

    assert buttons[Color.GREEN].isChecked()
    assert colors.value() is Color.GREEN


def test_value_changed_emits_the_new_value_once_per_change(parent):
    colors, buttons = make_group(parent)
    colors.set_value(Color.RED)
    values = []
    colors.value_changed.connect(values.append)

    buttons[Color.GREEN].click()
    colors.set_value(Color.RED)

    assert values == [Color.GREEN, Color.RED]


def test_lives_as_long_as_its_group(parent):
    colors, _ = make_group(parent)

    assert colors.parent() is not None
