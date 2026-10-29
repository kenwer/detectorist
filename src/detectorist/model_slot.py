"""One model the Pipeline holds, loaded on a pool thread, so a load of several seconds blocks neither the GUI nor inference."""
import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QThreadPool, Signal

from .utils import FileStamp

logger = logging.getLogger(__name__)


class ModelSlot(QObject):
    """
    Loads a model with factory(path, *args) in the background and reports it,
    unless another load() or drop() came after, so only the model wanted last
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
        # Counts load() and drop(), so a result of an earlier load is recognized as superseded
        self._generation = 0
        # The model reported last, which the InferenceWorker holds
        self.model_id: FileStamp | None = None
        # The model being loaded
        self.loading: FileStamp | None = None
        # Whether a model was asked for since the last drop(), even if it failed to load
        self.requested = False
        self._done.connect(self._on_done)
        self._error.connect(self._on_error)

    @property
    def expected(self) -> bool:
        """Whether a model is loaded or on its way. False for none asked for and for one that failed."""
        return self.model_id is not None or self.loading is not None

    def wants(self, path: str) -> bool:
        """Whether the model at path is loaded or being loaded."""
        try:
            model_id = FileStamp.from_path(path)
        except OSError:
            return False
        return model_id in (self.model_id, self.loading)

    def load(self, path: str, *args) -> None:
        """Drops the current model and loads the one at path. A file that cannot be read fails right away."""
        self.drop()
        self.requested = True
        try:
            model_id = FileStamp.from_path(path)
        except OSError as e:
            self.failed.emit(str(e))
            return
        self.loading = model_id
        generation = self._generation
        self._pool.start(lambda: self._load(generation, model_id, path, args))

    def drop(self) -> None:
        """Forgets the model, and the one being loaded, which is then not reported."""
        self._generation += 1
        self.model_id = None
        self.loading = None
        self.requested = False

    def shutdown(self) -> None:
        """Drops the model and waits for the loads under way."""
        self.drop()
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
        self.loading = None
        self.model_id = model_id
        self.loaded.emit(model, path)

    def _on_error(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self.loading = None
        self.failed.emit(message)
