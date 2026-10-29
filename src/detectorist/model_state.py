"""
Where the Pipeline's models are, as plain values the scheduling rules can
take without Qt. Qt-free so they can be unit-tested headless.
"""
from dataclasses import dataclass
from enum import Enum, auto

from .utils import FileStamp


class ModelState(Enum):
    """
    Where a ModelLoader is with its model. load() goes to LOADING, or to
    FAILED for a file that cannot be read, a finished load to LOADED or
    FAILED, and unload() back to NONE.
    """
    NONE = auto()  # no model asked for
    LOADING = auto()
    LOADED = auto()
    FAILED = auto()  # asked for, but it failed to load

    @property
    def is_loaded_or_loading(self) -> bool:
        """Whether results of the model will come, now or once it is loaded."""
        return self in (ModelState.LOADING, ModelState.LOADED)


@dataclass(frozen=True)
class Models:
    """The detector and the classifier as the Pipeline has them at one moment."""
    detector_id: FileStamp | None  # set once loaded, the stamp a DetectJob carries
    detector_state: ModelState
    classifier_id: FileStamp | None  # set once loaded, the stamp a ClassifyJob carries
    classifier_state: ModelState
    patterns: tuple[str, ...]  # the detection classes the classifier names
