"""
The requests, jobs and identities the Pipeline passes between the GUI thread
and its lanes. Qt-free so they can be unit-tested headless.

Jobs compare by identity: the Pipeline matches a job a lane hands back
against the one it sent, never against another job with equal fields.
"""
import os
import threading
from dataclasses import dataclass

from .image_object import ImageObject
from .structures import Box
from .utils import long_path


class CancelToken:
    """Tells a lane that the job carrying it is no longer wanted. Checked between steps."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class FileStamp:
    """The version of a file a cached result was computed from."""
    mtime_ns: int
    size: int

    @classmethod
    def from_path(cls, path: str) -> FileStamp:
        stat = os.stat(long_path(path))
        return cls(stat.st_mtime_ns, stat.st_size)


@dataclass(frozen=True)
class ModelId:
    """
    Which model a job runs with. A re-downloaded model gets another mtime,
    so results of the replaced file are recognized as stale too.
    """
    filename: str
    mtime_ns: int

    @classmethod
    def from_path(cls, path: str) -> ModelId:
        return cls(os.path.basename(path), os.stat(long_path(path)).st_mtime_ns)


@dataclass(frozen=True)
class ShowRequest:
    """What the UI wants to see. Sending the same request again is harmless."""
    path: str
    exposure_correction: bool
    detection_threshold: float


@dataclass(eq=False)
class DecodeJob:
    """
    Decode an image and build its display array, exposure corrected as
    exposure_correction says. A batch job builds none, as its image is never
    shown, and sets the image's exposure flag for the export instead.
    """
    path: str
    exposure_correction: bool
    token: CancelToken
    for_batch: bool = False


@dataclass(eq=False)
class RedisplayJob:
    """Rebuild the display array of a decoded image, e.g. after the exposure checkbox changed."""
    path: str
    image: ImageObject
    exposure_correction: bool
    token: CancelToken


@dataclass(eq=False)
class DetectJob:
    path: str
    image: ImageObject
    stamp: FileStamp  # the version of the file image was decoded from
    model_id: ModelId
    token: CancelToken


@dataclass(eq=False)
class ClassifyJob:
    path: str
    image: ImageObject
    boxes: list[Box]
    model_id: ModelId
    token: CancelToken
