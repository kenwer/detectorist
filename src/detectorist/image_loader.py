"""
The decode lane: decodes images and builds their display arrays on a thread
of their own, so neither blocks the GUI thread or waits for inference.
"""
import logging

from PySide6.QtCore import QObject, Signal, Slot

from .image_object import ImageObject
from .jobs import DecodeJob, RedisplayJob

logger = logging.getLogger(__name__)


class ImageLoader(QObject):
    """
    Runs one DecodeJob or RedisplayJob at a time and answers each with
    exactly one of loaded, redisplayed, failed or cancelled. The Pipeline
    decides what to decode and when, this class keeps no state between jobs.
    """
    loaded = Signal(object, object, object)  # DecodeJob, ImageObject, display array or None
    redisplayed = Signal(object, object)  # RedisplayJob, display array
    failed = Signal(object, str)  # job, message
    cancelled = Signal(object)  # job

    @Slot(object)
    def run(self, job: DecodeJob | RedisplayJob):
        if job.token.cancelled:
            self.cancelled.emit(job)
            return
        try:
            if isinstance(job, RedisplayJob):
                self.redisplayed.emit(job, job.image.display_rgb_8bit(job.exposure_correction))
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
        if job.for_batch:
            image.exposure_correction = job.exposure_correction
            self.loaded.emit(job, image, None)
        else:
            self.loaded.emit(job, image, image.display_rgb_8bit(job.exposure_correction))
