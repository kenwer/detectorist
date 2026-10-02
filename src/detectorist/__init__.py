from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("detectorist")
except PackageNotFoundError:
    __version__ = "unknown"
