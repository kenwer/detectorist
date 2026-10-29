"""
The decode lane: decodes images and builds their display arrays on a thread
of their own, so neither blocks the GUI thread or waits for inference.
"""
import logging

from PySide6.QtCore import QObject, Signal, Slot

from .image_object import ImageObject
from .jobs import DecodeJob, DisplayJob

logger = logging.getLogger(__name__)


class ImageWorker(QObject):
    """
    Runs one DecodeJob or DisplayJob at a time and answers each with exactly
    one of decoded, displayed, failed or cancelled. The Pipeline decides what
    to decode and display and when, this class keeps no state between jobs.
    """
    decoded = Signal(object, object)  # DecodeJob, ImageObject
    displayed = Signal(object, object)  # DisplayJob, display array
    failed = Signal(object, str)  # job, message
    cancelled = Signal(object)  # job

    @Slot(object)
    def run(self, job: DecodeJob | DisplayJob):
        if job.token.cancelled:
            self.cancelled.emit(job)
            return
        try:
            if isinstance(job, DisplayJob):
                self.displayed.emit(job, job.image.display_rgb_8bit(job.exposure_correction))
            else:
                self._decode(job)
        except Exception as e:
            logger.warning("Could not load %s: %s", job.path, e)
            self.failed.emit(job, f"Could not load image: {e}")

    def _decode(self, job: DecodeJob):
        image = ImageObject.create(job.path)
        if not image:
            self.failed.emit(job, "Could not load image.")
            return
        if job.token.cancelled:
            self.cancelled.emit(job)
            return
        self.decoded.emit(job, image)
