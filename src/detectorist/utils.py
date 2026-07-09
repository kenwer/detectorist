import os
import sys

from PySide6.QtCore import QStandardPaths


def get_model_path() -> str:
    """
    Get the path to the models directory.

    If a local ./models/ directory exists and contains model files and a models.json manifest,
    use it (covers running from source or a local development checkout).
    Otherwise, use the platform user data directory (QStandardPaths.AppDataLocation/models).
    The directory is created if it doesn't exist.

    Returns:
        str: The absolute path to the models directory.
    """
    local_models = os.path.realpath(os.path.normpath(os.path.join(os.getcwd(), "models")))
    if (os.path.isdir(local_models)
            and os.path.isfile(os.path.join(local_models, "models.json"))
            and any(f.endswith(".onnx") or f.endswith(".onnx.gz") for f in os.listdir(local_models))):
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


def strip_model_ext(filename: str) -> str:
    """Strip .onnx or .onnx.gz extension for display."""
    return filename.removesuffix(".gz").removesuffix(".onnx")


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

    if starts_with_home:
        path = "~" + path[len(home):]

    return path

