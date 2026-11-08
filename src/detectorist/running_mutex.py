"""A named Windows mutex that says Detectorist is running.

The Inno Setup installer waits while it exists, so an update started by the
app never copies files the exiting app still holds open. Windows releases it
when the process ends, however it ends.
"""

import functools
import sys

# Must match RunningMutex in packaging/windows/detectorist.iss
MUTEX_NAME = "DetectoristRunning"
_SYNCHRONIZE = 0x00100000

_handle: object | None = None


def hold_running_mutex() -> None:
    """Create the mutex on Windows and hold it for the life of the process.

    Closing it early would let an update start while the app still runs.
    """
    global _handle
    if sys.platform == "win32":
        _handle = _kernel32().CreateMutexW(None, False, MUTEX_NAME)


def other_instance_running() -> bool:
    """Whether another Detectorist holds the mutex too.

    Briefly drops this process's own handle, since a mutex cannot say how many
    processes hold it, then takes it again.
    """
    global _handle
    if sys.platform != "win32" or not _handle:
        return False
    kernel32 = _kernel32()
    kernel32.CloseHandle(_handle)
    probe = kernel32.OpenMutexW(_SYNCHRONIZE, False, MUTEX_NAME)
    if probe:
        kernel32.CloseHandle(probe)
    _handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return bool(probe)


@functools.cache
def _kernel32():
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    return kernel32
