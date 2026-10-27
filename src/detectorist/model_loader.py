"""Loads a model on a pool thread, so a load of several seconds blocks neither the GUI nor inference."""
import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QThreadPool, Signal

from .jobs import ModelId

logger = logging.getLogger(__name__)


class ModelLoader(QObject):
    """
    Calls factory(*args) once on a pool thread and reports the model or the
    error. Lives on the GUI thread, so its signals arrive there. The caller
    keeps a reference until one of them arrived.
    """
    loaded = Signal(object, object)  # model_id, model
    failed = Signal(object, str)  # model_id, message

    def __init__(self, factory: Callable[..., object], args: tuple, model_id: ModelId):
        super().__init__()
        self._factory = factory
        self._args = args
        self.model_id = model_id

    def start(self) -> None:
        QThreadPool.globalInstance().start(self._load)

    def _load(self) -> None:
        try:
            model = self._factory(*self._args)
        except Exception as e:
            logger.error("Could not load model %s: %s", self.model_id.filename, e)
            self.failed.emit(self.model_id, str(e))
            return
        self.loaded.emit(self.model_id, model)
