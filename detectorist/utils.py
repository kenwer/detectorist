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
