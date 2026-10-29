import gzip
import os
import re
import subprocess
import sys
from dataclasses import dataclass

from PySide6.QtCore import QFile, QIODeviceBase, QStandardPaths

from .model_downloader import CLASSIFICATION_MODELS_DIRNAME, MANIFEST_FILENAME


def physical_memory_bytes() -> int:
    """The machine's physical memory in bytes, or 16 GB if it cannot be read."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
            return 16 * 10**9
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return 16 * 10**9


def get_model_path() -> str:
    """
    Get the path to the models directory.

    If a local ./models/ directory exists and contains model files, a models.json manifest
    and a classifiers/models.json manifest, use it (covers running from source or a local
    development checkout).
    Otherwise, use the platform user data directory (QStandardPaths.AppDataLocation/models).
    The directory is created if it doesn't exist.

    Returns:
        str: The absolute path to the models directory.
    """
    local_models = os.path.realpath(os.path.normpath(os.path.join(os.getcwd(), "models")))
    if (os.path.isdir(local_models)
            and os.path.isfile(os.path.join(local_models, MANIFEST_FILENAME))
            and os.path.isfile(os.path.join(local_models, CLASSIFICATION_MODELS_DIRNAME, MANIFEST_FILENAME))
            and list_model_files(local_models)):
        return local_models

    # Default: platform user data directory
    data_location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    models_dir = os.path.join(data_location, "models")
    os.makedirs(models_dir, exist_ok=True)
    return models_dir


def long_path(path: str) -> str:
    """
    Make a path safe for writing on Windows, where the legacy Win32 file APIs
    reject paths longer than MAX_PATH (260 characters).

    On Windows this returns the path in extended-length form (prefixed with
    ``\\\\?\\``), which bypasses the MAX_PATH limit. Extended-length paths are
    passed to the filesystem verbatim, so the path must be absolute, normalized
    and use backslashes only (forward slashes are NOT translated). UNC paths use
    the ``\\\\?\\UNC\\`` form.

    On non-Windows platforms the path is returned unchanged.
    """
    if sys.platform != "win32":
        return path
    abs_path = os.path.normpath(os.path.abspath(path))
    if abs_path.startswith("\\\\?\\"):
        return abs_path
    if abs_path.startswith("\\\\"):  # UNC path: \\server\share -> \\?\UNC\server\share
        return "\\\\?\\UNC\\" + abs_path[2:]
    return "\\\\?\\" + abs_path


@dataclass(frozen=True)
class FileStamp:
    """
    A file as of its last write. A decoded image and its cached results keep
    the stamp of the image file, a job keeps the one of its model file, so
    both are recognized as stale once the file is rewritten or replaced.
    """
    path: str
    mtime_ns: int
    size: int

    @classmethod
    def from_path(cls, path: str) -> FileStamp:
        stat = os.stat(long_path(path))
        return cls(path, stat.st_mtime_ns, stat.st_size)


def resolve_short_path(path: str) -> str:
    """
    Resolve a Windows short (8.3) path component back to its real long name.

    Windows Explorer substitutes the 8.3 alias for the final path component
    in drag-and-drop data (the legacy CF_HDROP format) whenever the real long
    path would exceed MAX_PATH, so a path handed to us via a drop event can
    carry a short alias like "HOLOCE~1.HIF" even though the file's actual name
    on disk is unchanged and long. os.path.realpath() resolves this: opening
    the short alias itself stays under MAX_PATH, and the resolved path it
    returns has no MAX_PATH limit.

    On non-Windows platforms the path is returned unchanged.
    """
    if sys.platform != "win32":
        return path
    return os.path.realpath(path)


def list_model_files(folder: str) -> list[str]:
    """Sorted names of the model files (.onnx, .onnx.gz) in the folder. Empty if it does not exist."""
    try:
        entries = os.listdir(folder)
    except FileNotFoundError:
        return []
    return sorted(f for f in entries if f.endswith((".onnx", ".onnx.gz")))


def count_noun(number: int, noun: str) -> str:
    """A number with a noun in the matching form, e.g. "1 classification" or "20 classifications"."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def strip_model_ext(filename: str) -> str:
    """Strip .onnx or .onnx.gz extension for display."""
    return filename.removesuffix(".gz").removesuffix(".onnx")


def load_model_bytes(model_path: str) -> bytes:
    """Read an ONNX model file, transparently decompressing gzip if needed."""
    if model_path.endswith(".gz"):
        with gzip.open(model_path, 'rb') as f:
            return f.read()
    with open(model_path, 'rb') as f:
        return f.read()


def get_base_path():
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return base_path


def contract_user_path(path: str) -> str:
    """Contract the user's home directory to ~ for display purposes.

    This is the inverse of os.path.expanduser(). Useful for displaying
    paths in a more compact, user-friendly format.

    Args:
        path: A file path (absolute, relative, or with ~).

    Returns:
        The absolute path with the home directory replaced by ~, or the
        absolute path if it doesn't start with the home directory.

    Examples:
        >>> contract_user_path("/home/ken/Pictures")
        '~/Pictures'
        >>> contract_user_path("~/Documents")
        '~/Documents'
        >>> contract_user_path("Downloads")  # relative to cwd in home
        '~/Downloads'
        >>> contract_user_path("/var/log")
        '/var/log'
    """
    # Expand ~ and convert to absolute path
    home = os.path.expanduser("~")
    path = os.path.abspath(os.path.expanduser(path))

    # Check if the path starts with the home directory
    # (case-insensitive on Windows, case-sensitive otherwise)
    if sys.platform == "win32":
        starts_with_home = path.lower().startswith(home.lower())
    else:
        starts_with_home = path.startswith(home)

    rest = path[len(home):]
    if starts_with_home and (not rest or rest.startswith(os.sep)):
        path = "~" + rest

    return path


def reveal_in_file_manager(path: str) -> None:
    """Opens a folder in the native (OS specific) file manager, revealing the file if a file path is provided."""
    path = os.path.normpath(path)
    if sys.platform == 'win32':  # Windows
        if os.path.isfile(path):
            subprocess.Popen(['explorer', '/select,', path])
        else:
            subprocess.Popen(['explorer', path])
    elif sys.platform == 'darwin':  # macOS
        if os.path.isfile(path):
            subprocess.Popen(['open', '-R', path])
        else:
            subprocess.Popen(['open', path])
    elif os.name == 'posix':  # Linux
        dir_path = os.path.dirname(path) if os.path.isfile(path) else path
        subprocess.Popen(['xdg-open', dir_path])


def file_manager_name(platform: str = sys.platform) -> str:
    """The name users know the platform's file manager by, as in "Reveal in Finder"."""
    if platform == "darwin":
        return "Finder"
    if platform == "win32":
        return "File Explorer"
    return "File Manager"


def read_resource_text(path: str) -> str:
    resource = QFile(path)
    if not resource.open(QIODeviceBase.OpenModeFlag.ReadOnly | QIODeviceBase.OpenModeFlag.Text):
        return ""
    text = resource.readAll().data().decode("utf-8")
    resource.close()
    return text


def readme_section(markdown: str, heading: str, level: int = 2) -> str:
    """Return the body of a README section, up to the next heading of the same or a higher level."""
    _, found, rest = markdown.partition(f"\n{'#' * level} {heading}\n")
    if not found:
        return ""
    return re.split(rf"\n#{{1,{level}}} ", rest, maxsplit=1)[0].strip()
