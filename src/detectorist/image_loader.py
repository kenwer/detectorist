"""
The decode lane: decodes images and builds their display arrays on a thread
of their own, so neither blocks the GUI thread or waits for inference.
"""
import logging

from PySide6.QtCore import QObject, Signal, Slot

from .image_object import ImageObject
from .jobs import DecodeJob, FileStamp

logger = logging.getLogger(__name__)


class ImageLoader(QObject):
    """
    Runs one DecodeJob at a time and answers each with exactly one of
    loaded, failed or cancelled. The Pipeline decides what to decode and
    when, this class keeps no state between jobs.
    """
    loaded = Signal(object, object, object, object)  # job, ImageObject, display array, FileStamp or None
    failed = Signal(object, str)  # job, message
    cancelled = Signal(object)  # job

    @Slot(object)
    def run(self, job: DecodeJob):
        """
        Decodes job.path, or with job.image set only rebuilds its display
        array, e.g. after the exposure checkbox changed. Such a job reports
        no stamp, as the file was not read again.
        """
        if job.token.cancelled:
            self.cancelled.emit(job)
            return
        try:
            if job.image is not None:
                self.loaded.emit(job, job.image, job.image.display_rgb_8bit(job.exposure_correction), None)
                return
            # Read before decoding, so a file changing meanwhile looks changed the next time
            stamp = FileStamp.of(job.path)
            image = ImageObject.create(job.path)
            if not image:
                self.failed.emit(job, "Could not load image.")
                return
            if job.token.cancelled:
                self.cancelled.emit(job)
                return
            if job.for_batch:
                image.exposure_correction = job.exposure_correction
            self.loaded.emit(job, image, image.display_rgb_8bit(job.exposure_correction), stamp)
        except Exception as e:
            logger.warning("Could not load %s: %s", job.path, e)
            self.failed.emit(job, f"Could not load image: {e}")
