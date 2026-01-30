import os
import sys


# Determine the path based on compilation mode
def get_model_path(directory: str="models") -> str:
    """
    Get the path to the models directory, handling different compilation scenarios.

    Args:
        directory (str, optional): The subdirectory name. Defaults to "models".

    Returns:
        str: The absolute path to the models directory.
    """
    if "__compiled__" in globals() or "NUITKA_ONEFILE_PARENT" in os.environ or getattr(sys, 'frozen', False):
        # running in compiled mode
        # root directory of inside the AppBundle (macOS) or OneFileTempDir (windows)
        project_dir = os.path.dirname(sys.modules['__main__'].__file__)
    else:
        # running in script mode
        project_dir = os.getcwd()

    return os.path.realpath(os.path.normpath(os.path.join(project_dir, directory)))


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

