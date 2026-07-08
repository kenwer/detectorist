import json
from pathlib import Path
from typing import TypeVar, cast

from PySide6.QtCore import QByteArray, QDir, QSettings

from detectorist import __version__

from . import utils

T = TypeVar("T")


class Settings:
    """Settings class that uses QSettings for persistent settings management."""

    ORGANIZATION = "kenwer"
    APPLICATION = "detectorist"

    # Settings groups
    GROUP_APP = "app"        # app metadata (not exported)
    GROUP_UI = "ui"          # window geometry/layout (not exported)
    GROUP_RECENT = "recent"  # recently opened locations (not exported)
    GROUP_MODEL = "model"    # model settings such as model path and confidence
    GROUP_CROP = "crop"      # crop settings such as mode, aspect ratio, padding, etc.

    # App settings (not exported)
    KEY_VERSION = "version"

    # Recent locations (not exported)
    KEY_RECENT_DIRECTORIES = "directories"
    MAX_RECENT_DIRECTORIES = 10

    # UI settings (not exported)
    KEY_WINDOW_GEOMETRY = "geometry"
    KEY_WINDOW_SPLITTER = "splitter_state"

    # Model settings
    KEY_MODEL_PATH = "path"

    # Crop settings
    KEY_CONFIDENCE = "confidence"
    KEY_CROP_MODE = "mode"
    KEY_ASPECT_RATIO_INDEX = "aspect_ratio_index"
    KEY_PADDING = "padding"
    KEY_AUTO_CORRECT_EXPOSURE = "auto_correct_exposure"

    def __init__(self):
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)

    def _get_grouped(self, group: str, key: str, type_hint: type[T]) -> T | None:
        """Get a typed setting value from a group, or None if the key doesn't exist."""
        self._settings.beginGroup(group)
        value = None
        if self._settings.contains(key):
            value = cast(T, self._settings.value(key, type=type_hint))
        self._settings.endGroup()
        return value

    def _set_grouped(self, group: str, key: str, value: object) -> None:
        """Set a setting value within a group."""
        self._settings.beginGroup(group)
        self._settings.setValue(key, value)
        self._settings.endGroup()

    def _get_grouped_with_default(
        self, group: str, key: str, default: T, type_hint: type[T]
    ) -> T:
        """Get a typed setting value from a group, with a default if not set."""
        self._settings.beginGroup(group)
        value = cast(T, self._settings.value(key, default, type=type_hint))
        self._settings.endGroup()
        return value

    # GROUP_APP settings
    @property
    def version(self) -> str | None:
        """Return the app version that last saved settings, or None if not set."""
        return self._get_grouped(self.GROUP_APP, self.KEY_VERSION, str)

    def save_current_version(self) -> None:
        """Save the current app version to settings."""
        self._set_grouped(self.GROUP_APP, self.KEY_VERSION, __version__)

    # GROUP_RECENT settings

    @property
    def last_directory(self) -> str:
        """Last opened directory for file dialogs (defaults to home directory)."""
        recent = self.recent_directories
        return recent[0] if recent else QDir.homePath()

    @property
    def recent_directories(self) -> list[str]:
        """List of recently opened directories, most recent first."""
        self._settings.beginGroup(self.GROUP_RECENT)
        value = self._settings.value(self.KEY_RECENT_DIRECTORIES, [], type=list)
        self._settings.endGroup()
        return cast(list[str], value)

    def add_recent_directory(self, path: str) -> None:
        """Add a directory to the recent list (moves to front if already present)."""
        recent = self.recent_directories

        # Remove if already present (will be re-added at front)
        if path in recent:
            recent.remove(path)

        # Add to front, trim to max size
        recent.insert(0, path)
        recent = recent[: self.MAX_RECENT_DIRECTORIES]

        self._settings.beginGroup(self.GROUP_RECENT)
        self._settings.setValue(self.KEY_RECENT_DIRECTORIES, recent)
        self._settings.endGroup()

    def clear_recent_directories(self) -> None:
        """Clear the recent directories list."""
        self._settings.beginGroup(self.GROUP_RECENT)
        self._settings.remove(self.KEY_RECENT_DIRECTORIES)
        self._settings.endGroup()

    # GROUP_UI settings
    @property
    def window_geometry(self) -> QByteArray | None:
        return self._get_grouped(self.GROUP_UI, self.KEY_WINDOW_GEOMETRY, QByteArray)

    @window_geometry.setter
    def window_geometry(self, value: QByteArray) -> None:
        self._set_grouped(self.GROUP_UI, self.KEY_WINDOW_GEOMETRY, value)

    @property
    def splitter_state(self) -> QByteArray | None:
        return self._get_grouped(self.GROUP_UI, self.KEY_WINDOW_SPLITTER, QByteArray)

    @splitter_state.setter
    def splitter_state(self, value: QByteArray) -> None:
        self._set_grouped(self.GROUP_UI, self.KEY_WINDOW_SPLITTER, value)

    # GROUP_MODEL settings
    @property
    def model(self) -> str | None:
        return self._get_grouped(self.GROUP_MODEL, self.KEY_MODEL_PATH, str)

    @model.setter
    def model(self, value: str) -> None:
        self._set_grouped(self.GROUP_MODEL, self.KEY_MODEL_PATH, value)

    @property
    def confidence(self) -> int | None:
        return self._get_grouped(self.GROUP_MODEL, self.KEY_CONFIDENCE, int)

    @confidence.setter
    def confidence(self, value: int) -> None:
        self._set_grouped(self.GROUP_MODEL, self.KEY_CONFIDENCE, value)

    # GROUP_CROP settings
    @property
    def crop_mode(self) -> str | None:
        return self._get_grouped(self.GROUP_CROP, self.KEY_CROP_MODE, str)

    @crop_mode.setter
    def crop_mode(self, value: str) -> None:
        self._set_grouped(self.GROUP_CROP, self.KEY_CROP_MODE, value)

    @property
    def aspect_ratio_index(self) -> int | None:
        return self._get_grouped(self.GROUP_CROP, self.KEY_ASPECT_RATIO_INDEX, int)

    @aspect_ratio_index.setter
    def aspect_ratio_index(self, value: int) -> None:
        self._set_grouped(self.GROUP_CROP, self.KEY_ASPECT_RATIO_INDEX, value)

    @property
    def padding(self) -> int | None:
        return self._get_grouped(self.GROUP_CROP, self.KEY_PADDING, int)

    @padding.setter
    def padding(self, value: int) -> None:
        self._set_grouped(self.GROUP_CROP, self.KEY_PADDING, value)

    @property
    def auto_correct_exposure_enabled(self) -> bool | None:
        return self._get_grouped(self.GROUP_CROP, self.KEY_AUTO_CORRECT_EXPOSURE, bool)

    @auto_correct_exposure_enabled.setter
    def auto_correct_exposure_enabled(self, value: bool) -> None:
        self._set_grouped(self.GROUP_CROP, self.KEY_AUTO_CORRECT_EXPOSURE, value)

    def export_group(self, group: str) -> dict[str, object]:
        """Export all settings in a group as a dict."""
        data: dict[str, object] = {}
        self._settings.beginGroup(group)
        for key in self._settings.childKeys():
            data[key] = self._settings.value(key)
        self._settings.endGroup()
        return data

    def import_group(self, group: str, data: dict[str, object]) -> None:
        """Import settings into a group from a dict."""
        self._settings.beginGroup(group)
        for key, value in data.items():
            self._settings.setValue(key, value)
        self._settings.endGroup()

    def export_to_file(self, path: Path, groups: list[str]) -> None:
        """Export specified groups to a JSON file."""
        data = {
            "app_version": __version__,
            "groups": {g: self.export_group(g) for g in groups},
        }
        with open(utils.long_path(str(path)), "w") as f:
            f.write(json.dumps(data, indent=2))

    def import_from_file(self, path: Path, groups: list[str] | None = None) -> None:
        """Import groups from a JSON file. If groups is None, import all."""
        with open(utils.long_path(str(path))) as f:
            data = json.loads(f.read())
        for group, settings in data.get("groups", {}).items():
            if groups is None or group in groups:
                self.import_group(group, settings)
