import json
from pathlib import Path
from typing import Any, Self, overload

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QByteArray, QDir, QSettings

from detectorist import __version__

from . import utils


class Setting[T]:
    """
    One stored setting, read back as its type, or None while it is unset.
    Setting it to None unsets it, since an INI file has no way to store None.
    The key is the attribute name without its group prefix, unless given.
    """

    def __init__(self, group: str, value_type: type[T], doc: str, key: str = ""):
        self.group = group
        self.type = value_type
        self.__doc__ = doc
        self.key = key

    def __set_name__(self, owner: type, name: str) -> None:
        self.key = self.key or name.removeprefix(f"{self.group}_")

    @property
    def path(self) -> str:
        return f"{self.group}/{self.key}"

    @overload
    def __get__(self, settings: None, owner: type | None = None) -> Self: ...

    @overload
    def __get__(self, settings: Settings, owner: type | None = None) -> T | None: ...

    def __get__(self, settings: Settings | None, owner: type | None = None) -> Self | T | None:
        if settings is None:
            return self
        return settings._read(self)

    def __set__(self, settings: Settings, value: T | None) -> None:
        settings._write(self, value)


class Settings:
    """
    The app's settings, stored with QSettings. Each one is a Setting class
    attribute named after its key, prefixed by its group where the key alone
    would be unclear, like crop_mode. The portable groups describe
    how images are detected, classified and exported, and are what settings
    files hold. The other groups describe this computer.
    """

    ORGANIZATION = "kenwer"
    APPLICATION = "detectorist"

    # Settings groups
    GROUP_APP = "app"        # app metadata (not exported)
    GROUP_UI = "ui"          # window geometry and layout (not exported)
    GROUP_RECENT = "recent"  # recently opened folders (not exported)
    GROUP_MODEL = "model"    # detection and classification models and their confidences
    GROUP_IMAGE = "image"    # how images are shown and exported, such as exposure correction
    GROUP_CROP = "crop"      # whether and how Export crops: mode, aspect ratio and padding
    # The groups settings files hold, in the order they list them
    PORTABLE_GROUPS = [GROUP_MODEL, GROUP_IMAGE, GROUP_CROP]

    MAX_RECENT_FOLDERS = 10

    # App settings (not exported)
    newest_version = Setting(GROUP_APP, str,
                             "The newest app version that saved the settings, like 0.12.1.dev3. An older one leaves it.")

    # UI settings (not exported)
    window_geometry = Setting(GROUP_UI, QByteArray, "Main window size and position, as saved by QWidget.saveGeometry().")
    main_splitter_state = Setting(GROUP_UI, QByteArray,
                                  "Sizes of the main splitter's panes, as saved by QSplitter.saveState().")
    image_splitter_state = Setting(GROUP_UI, QByteArray,
                                   "Heights of the image and the results below it, as saved by QSplitter.saveState().")

    # Recent folders (not exported), read through recent_folders. The key keeps
    # its name from earlier versions, so their lists carry over.
    _recent_folders = Setting(GROUP_RECENT, list, "Recently opened folders, most recent first.", key="directories")

    # Model settings
    detection_model = Setting(GROUP_MODEL, str, "File name of the selected detection model.")
    detection_min_confidence_percent = Setting(
        GROUP_MODEL, int, "Minimum score in percent (1 to 100) a detection must reach to be kept.")
    classification_model = Setting(GROUP_MODEL, str,
                                   "File name of the selected classifier, or None when none is selected.")
    classification_min_confidence_percent = Setting(
        GROUP_MODEL, int,
        "Minimum score in percent (1 to 100) a family, genus or species must reach for its name "
        "to be shown and written to the classification CSV.")

    # Image settings
    image_correct_exposure = Setting(GROUP_IMAGE, bool,
                                     "Whether images are shown and exported with the camera's exposure bias corrected.")

    # Crop settings
    crop_mode = Setting(GROUP_CROP, str,
                        "The CropMode value of the selected crop mode. Parse it with CropMode.from_setting().")
    crop_aspect_ratio = Setting(GROUP_CROP, str,
                                "The crop aspect ratio, such as \"3:2\", \"source_image\" or \"detection_frame\".")
    crop_padding_percent = Setting(GROUP_CROP, int,
                                   "Padding added around a crop, in percent of the detection's width and height.")
    crop_images = Setting(GROUP_CROP, bool, "Whether Export crops the images or copies them whole.")

    def __init__(self, qsettings: QSettings | None = None):
        """
        Args:
            qsettings: The store to read and write. Defaults to the per-user
                native store for this application.
        """
        self._settings = qsettings if qsettings is not None else QSettings(self.ORGANIZATION, self.APPLICATION)
        # Keys a newer build saved are left alone, so going back to an older build keeps them
        if not self._saved_by_newer_build():
            self._remove_unknown_keys()

    @classmethod
    def _all(cls) -> list[Setting]:
        return [value for value in vars(cls).values() if isinstance(value, Setting)]

    @classmethod
    def _portable(cls) -> list[Setting]:
        return [setting for setting in cls._all() if setting.group in cls.PORTABLE_GROUPS]

    def _remove_unknown_keys(self) -> None:
        """
        Removes the keys earlier versions wrote under other names, which would
        otherwise stay in the store for good. Keys outside the app's groups,
        like the system-wide ones macOS lists along, are left alone.
        """
        known = {setting.path for setting in self._all()}
        groups = {setting.group for setting in self._all()}
        for key in self._settings.allKeys():
            if key.split("/")[0] in groups and key not in known:
                self._settings.remove(key)

    def _read(self, setting: Setting) -> Any:
        if not self._settings.contains(setting.path):
            return None
        return self._settings.value(setting.path, type=setting.type)

    def _write(self, setting: Setting, value: Any) -> None:
        if value is None:
            self._settings.remove(setting.path)
        else:
            self._settings.setValue(setting.path, value)

    def _saved_by_newer_build(self) -> bool:
        """
        Whether a newer build than this one saved the settings, like 0.12.1.dev3
        after 0.12.0. A build whose own version does not parse, like "unknown"
        without package metadata, cannot tell and assumes so. A saved version
        that does not parse counts as older.
        """
        try:
            current = Version(__version__)
        except InvalidVersion:
            return True
        try:
            return self.newest_version is not None and Version(self.newest_version) > current
        except InvalidVersion:
            return False

    def save_current_version(self) -> None:
        """
        Records the app version, unless a newer build saved the settings. The
        version is kept then, so a later start of this build still leaves the
        newer build's keys alone.
        """
        if not self._saved_by_newer_build():
            self.newest_version = __version__

    @property
    def last_folder(self) -> str:
        """Last opened folder for file dialogs (defaults to home folder)."""
        recent = self.recent_folders
        return recent[0] if recent else QDir.homePath()

    @property
    def recent_folders(self) -> list[str]:
        return self._recent_folders or []

    def add_recent_folder(self, path: str) -> None:
        """Puts a folder first in the recent list, moving it there if it is already listed."""
        recent = [folder for folder in self.recent_folders if folder != path]
        self._recent_folders = [path, *recent][: self.MAX_RECENT_FOLDERS]

    def clear_recent_folders(self) -> None:
        self._recent_folders = None

    def reset_to_defaults(self) -> None:
        """Clears the portable settings, leaving recent folders and the window layout untouched."""
        for setting in self._portable():
            self._write(setting, None)

    def export_to_file(self, path: Path) -> None:
        """Writes the portable settings to a JSON file, an unset one as null."""
        groups: dict[str, dict[str, Any]] = {group: {} for group in self.PORTABLE_GROUPS}
        for setting in self._portable():
            groups[setting.group][setting.key] = self._read(setting)
        data = {"app_version": __version__, "settings": groups}
        with open(utils.long_path(str(path)), "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))

    def import_from_file(self, path: Path) -> None:
        """
        Reads the portable settings from a JSON file written by export_to_file().
        Settings the file leaves out keep their value, null unsets one, and
        unknown groups and keys are ignored.

        Raises:
            OSError: If the file cannot be read.
            ValueError: If the file is not JSON, not shaped like an export, or
                holds a value of the wrong type. Nothing is imported in that case.
        """
        with open(utils.long_path(str(path)), encoding="utf-8") as f:
            data = json.loads(f.read())
        # Checked in full before the first write, so a bad file changes nothing
        groups = data.get("settings") if isinstance(data, dict) else None
        if not isinstance(groups, dict) or not all(isinstance(v, dict) for v in groups.values()):
            raise ValueError(f"{path.name} is not a settings file")
        values = {setting: groups[setting.group][setting.key] for setting in self._portable()
                  if setting.key in groups.get(setting.group, {})}
        for setting, value in values.items():
            # type() and not isinstance(), since a JSON true is an int to Python
            if value is not None and type(value) is not setting.type:
                raise ValueError(f"{path.name} is not a settings file: {setting.group}.{setting.key} "
                                 f"must be a {setting.type.__name__}")
        for setting, value in values.items():
            self._write(setting, value)
