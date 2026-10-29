"""Loads one model of the Pipeline on a pool thread, so a load of several seconds blocks neither the GUI nor inference."""
import logging
from collections.abc import Callable
from enum import Enum, auto

from PySide6.QtCore import QObject, QThreadPool, Signal

from .utils import FileStamp

logger = logging.getLogger(__name__)


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


class ModelLoader(QObject):
    """
    Loads a model with factory(path, *args) in the background and reports it,
    unless another load() or unload() came after, so only the model wanted last
    is ever reported. Lives on the GUI thread, so its signals arrive there.
    """
    loaded = Signal(object, str)  # model, model path
    failed = Signal(str)  # message

    # From the pool thread: load generation, stamp of the model file, model, model path
    _done = Signal(int, object, object, str)
    _error = Signal(int, str)

    def __init__(self, factory: Callable[..., object], parent: QObject | None = None):
        super().__init__(parent)
        self._factory = factory
        self._pool = QThreadPool(self)
        self._generation = 0  # Counts load() and unload(), so a result of an earlier load is recognized as superseded
        self.model_id: FileStamp | None = None  # The model reported last, which the InferenceWorker holds
        self._loading: FileStamp | None = None  # The model being loaded
        self.state = ModelState.NONE
        self._done.connect(self._on_done)
        self._error.connect(self._on_error)

    @property
    def is_loaded_or_loading(self) -> bool:
        """Whether a model is there or on its way. False for none asked for and for one that failed to load."""
        return self.state in (ModelState.LOADING, ModelState.LOADED)

    def needs_load(self, path: str) -> bool:
        """
        Whether the model at path is neither loaded nor being loaded. True for
        a file that cannot be read, so load() reports why.
        """
        try:
            model_id = FileStamp.from_path(path)
        except OSError:
            return True
        return model_id not in (self.model_id, self._loading)

    def load(self, path: str, *args) -> None:
        """Unloads the current model and loads the one at path. A file that cannot be read fails right away."""
        self.unload()
        try:
            model_id = FileStamp.from_path(path)
        except OSError as e:
            self.state = ModelState.FAILED
            self.failed.emit(str(e))
            return
        self.state = ModelState.LOADING
        self._loading = model_id
        generation = self._generation
        self._pool.start(lambda: self._load(generation, model_id, path, args))

    def unload(self) -> None:
        """Forgets the model, and the one being loaded, which is then not reported."""
        self._generation += 1
        self.model_id = None
        self._loading = None
        self.state = ModelState.NONE

    def shutdown(self) -> None:
        """Unloads the model and waits for the loads under way."""
        self.unload()
        self._pool.waitForDone()

    def _load(self, generation: int, model_id: FileStamp, path: str, args: tuple) -> None:
        try:
            model = self._factory(path, *args)
        except Exception as e:
            logger.error("Could not load model %s: %s", path, e)
            self._error.emit(generation, str(e))
            return
        self._done.emit(generation, model_id, model, path)

    def _on_done(self, generation: int, model_id: FileStamp, model, path: str) -> None:
        if generation != self._generation:
            return
        self._loading = None
        self.model_id = model_id
        self.state = ModelState.LOADED
        self.loaded.emit(model, path)

    def _on_error(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._loading = None
        self.state = ModelState.FAILED
        self.failed.emit(message)
