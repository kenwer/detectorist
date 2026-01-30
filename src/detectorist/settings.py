from typing import TypeVar, cast

from PySide6.QtCore import QByteArray, QDir, QSettings

from ._version import __version__

T = TypeVar("T")


class Settings:
    """Settings class that uses QSettings for persistent settings management."""

    ORGANIZATION = "kenwer"
    APPLICATION = "detectorist"

    # Setting keys
    KEY_VERSION = "app_version" # the app version that last saved settings
    KEY_WINDOW_GEOMETRY = "window/geometry" # the main window geometry
    KEY_WINDOW_SPLITTER = "window/splitter_state" # the main window splitter state
    KEY_BASE_FOLDER = "settings/base_folder" # base folder for file dialogs
    KEY_MODEL = "settings/model" # selected model path
    KEY_CONFIDENCE = "settings/confidence" # confidence threshold (0-100 integer)
    KEY_CROP_MODE = "settings/crop_mode" # crop mode
    KEY_ASPECT_RATIO_INDEX = "settings/aspect_ratio_index" # aspect ratio combo box index
    KEY_PADDING = "settings/padding" # padding percentage (0-100 integer)
    KEY_AUTO_CORRECT_EXPOSURE_ENABLED = "settings/auto_correct_exposure_enabled" # auto correct camera exposure bias enabled (bool)

    # Crop mode constants
    CROP_TOP_CONFIDENCE = "top_confidence"
    CROP_LARGEST_AREA = "largest_area"
    CROP_ALL_DETECTED = "all_detected_objects"
    CROP_MOST_CENTERED = "most_centered"

    def __init__(self):
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)

    def _get_if_set(self, key: str, type_hint: type[T]) -> T | None:
        """Get a typed setting value, or None if the key doesn't exist.

        Unlike QSettings.value() which requires a default, this returns None for
        missing keys, allowing callers to distinguish "not set" from "set to default".

        The cast works around QSettings.value() returning 'object' in type stubs,
        even when type= is specified.
        """
        if self._settings.contains(key):
            return cast(T, self._settings.value(key, type=type_hint))
        return None

    # App version that wrote these settings
    @property
    def version(self) -> str | None:
        """Return the app version that last saved settings, or None if not set."""
        return self._get_if_set(self.KEY_VERSION, str)

    def save_current_version(self):
        """Save the current app version to settings."""
        self._settings.setValue(self.KEY_VERSION, __version__)

    # Window geometry and splitter state
    @property
    def window_geometry(self) -> QByteArray | None:
        return self._get_if_set(self.KEY_WINDOW_GEOMETRY, QByteArray)

    @window_geometry.setter
    def window_geometry(self, value: QByteArray):
        self._settings.setValue(self.KEY_WINDOW_GEOMETRY, value)

    @property
    def splitter_state(self) -> QByteArray | None:
        return self._get_if_set(self.KEY_WINDOW_SPLITTER, QByteArray)

    @splitter_state.setter
    def splitter_state(self, value: QByteArray):
        self._settings.setValue(self.KEY_WINDOW_SPLITTER, value)

    # Base folder for file dialogs (always has a default - home directory)
    @property
    def base_folder(self) -> str:
        return cast(str, self._settings.value(self.KEY_BASE_FOLDER, QDir.homePath(), type=str))

    @base_folder.setter
    def base_folder(self, value: str):
        self._settings.setValue(self.KEY_BASE_FOLDER, value)

    # Model selection
    @property
    def model(self) -> str | None:
        return self._get_if_set(self.KEY_MODEL, str)

    @model.setter
    def model(self, value: str):
        self._settings.setValue(self.KEY_MODEL, value)

    # Confidence threshold (0-100 integer for slider)
    @property
    def confidence(self) -> int | None:
        return self._get_if_set(self.KEY_CONFIDENCE, int)

    @confidence.setter
    def confidence(self, value: int):
        self._settings.setValue(self.KEY_CONFIDENCE, value)

    # Crop mode
    @property
    def crop_mode(self) -> str | None:
        return self._get_if_set(self.KEY_CROP_MODE, str)

    @crop_mode.setter
    def crop_mode(self, value: str):
        self._settings.setValue(self.KEY_CROP_MODE, value)

    # Aspect ratio (stored as combo box index)
    @property
    def aspect_ratio_index(self) -> int | None:
        return self._get_if_set(self.KEY_ASPECT_RATIO_INDEX, int)

    @aspect_ratio_index.setter
    def aspect_ratio_index(self, value: int):
        self._settings.setValue(self.KEY_ASPECT_RATIO_INDEX, value)

    # Padding percentage (0-100 integer for slider)
    @property
    def padding(self) -> int | None:
        return self._get_if_set(self.KEY_PADDING, int)

    @padding.setter
    def padding(self, value: int):
        self._settings.setValue(self.KEY_PADDING, value)

    # Auto correct camera exposure bias
    @property
    def auto_correct_exposure_enabled(self) -> bool | None:
        return self._get_if_set(self.KEY_AUTO_CORRECT_EXPOSURE_ENABLED, bool)

    @auto_correct_exposure_enabled.setter
    def auto_correct_exposure_enabled(self, value: bool):
        self._settings.setValue(self.KEY_AUTO_CORRECT_EXPOSURE_ENABLED, value)
