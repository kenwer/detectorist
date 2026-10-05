"""Tests for the name filter of the Open Image(s) dialog.

Which matcher reads the filter depends on the platform. Qt's own dialog and
the macOS dialog use QDir.match, which ignores case. The GTK dialog of Linux
desktops uses a case-sensitive glob, which fnmatchcase stands in for here.
"""

import re
from fnmatch import fnmatchcase

import pytest
from PySide6.QtCore import QDir

from detectorist.detectorist_app import image_name_filter
from detectorist.image_object import supported_extensions

# Names as cameras and people write them
IMAGES = ["lower.jpg", "UPPER.JPG", "Mixed.Jpg", "sony.HIF", "raw.ARW", "canon.CR3", "phone.heic"]
OTHERS = ["notes.txt", "image.jpg.bak", "jpg"]


def patterns_of(name_filter):
    return re.fullmatch(r"Images \((.*)\)", name_filter).group(1).split(" ")


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_plain_patterns_where_the_native_dialog_ignores_case(platform):
    patterns = patterns_of(image_name_filter(platform))

    assert patterns == ["*" + ext for ext in supported_extensions()]
    # Windows would take brackets literally and show no file at all
    assert not any("[" in pattern for pattern in patterns)


def test_linux_patterns_match_any_case_in_a_case_sensitive_dialog():
    patterns = patterns_of(image_name_filter("linux"))

    assert "*.[jJ][pP][gG]" in patterns
    assert "*.[cC][rR]3" in patterns
    for name in IMAGES:
        assert any(fnmatchcase(name, pattern) for pattern in patterns), name
    for name in OTHERS:
        assert not any(fnmatchcase(name, pattern) for pattern in patterns), name


def test_linux_patterns_also_work_in_qts_own_dialog():
    # The fallback when no desktop dialog is available
    patterns = patterns_of(image_name_filter("linux"))

    for name in IMAGES:
        assert QDir.match(patterns, name), name
    for name in OTHERS:
        assert not QDir.match(patterns, name), name


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_filter_has_the_form_qt_parses(platform):
    # Qt's own pattern for "Name (patterns)", from QPlatformFileDialogHelper::filterRegExp
    qt_filter = r"^(.*)\(([a-zA-Z0-9_.,*? +;#\-\[\]@\{\}/!<>\$%&=^~:\|]*)\)$"

    assert re.match(qt_filter, image_name_filter(platform))
