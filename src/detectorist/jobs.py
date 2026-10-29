"""
The requests, jobs and identities the Pipeline passes between the GUI thread
and its lanes. Qt-free so they can be unit-tested headless.

Jobs compare by identity: the Pipeline matches a job a lane hands back
against the one it sent, never against another job with equal fields. A job
that carries a decoded image takes its path from the image.
"""
import threading
from dataclasses import dataclass

from .image_object import ImageObject
from .structures import Box
from .utils import FileStamp


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
class ShowRequest:
    """What the UI wants to see. Sending the same request again is harmless."""
    path: str
    exposure_correction: bool
    detection_threshold: float


@dataclass(eq=False)
class DecodeJob:
    """Decode the image file at path into an ImageObject."""
    path: str
    token: CancelToken


@dataclass(eq=False)
class DisplayJob:
    """Build the 8-bit display array of a decoded image, exposure corrected as exposure_correction says."""
    image: ImageObject
    exposure_correction: bool
    token: CancelToken

    @property
    def path(self) -> str:
        return self.image.image_path


@dataclass(eq=False)
class DetectJob:
    image: ImageObject
    model_id: FileStamp
    token: CancelToken

    @property
    def path(self) -> str:
        return self.image.image_path


@dataclass(eq=False)
class ClassifyJob:
    image: ImageObject
    boxes: list[Box]
    model_id: FileStamp
    token: CancelToken

    @property
    def path(self) -> str:
        return self.image.image_path
