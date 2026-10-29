"""
Browsing: the image the user looks at and the neighbours to prefetch. Decides
what those images still need, which decode and inference job comes next, and
what is ready to report about the shown image. The Pipeline runs the jobs and
hands back what came of them, and reports to the window what Browsing returns.
Qt-free so it can be unit-tested headless.
"""
import os
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np

from .cache import ImageStore
from .image_object import ImageObject
from .jobs import CancelToken, ClassifyJob, DecodeJob, DetectJob, DisplayJob, ShowRequest
from .model_state import Models, ModelState
from .structures import Box, Detection, Taxonomy

# What has been reported for the current request, so each is reported once
IMAGE, DETECTIONS, NAMES, ERROR = "image", "detections", "names", "error"


class Work(Enum):
    """A step a path still needs, see Needs."""
    DECODE = auto()
    DISPLAY = auto()  # build the display array
    DETECT = auto()
    CLASSIFY = auto()  # name Needs.boxes
    WAIT = auto()  # results come once a model is loaded or the image is decoded


@dataclass(frozen=True)
class Needs:
    """What a path still needs from each lane. None means nothing more is coming: done, failed or no model."""
    image: Work | None  # DECODE or DISPLAY
    inference: Work | None  # DETECT, CLASSIFY or WAIT
    boxes: tuple[Box, ...] = ()  # the boxes to name, for CLASSIFY

    @property
    def settled(self) -> bool:
        return self.image is None and self.inference is None


# What Browsing reports to the window, one class per signal of the Pipeline

@dataclass(eq=False)
class ImageLoaded:
    path: str
    image: ImageObject
    display: np.ndarray


@dataclass(eq=False)
class DetectionComplete:
    path: str
    detections: list[Detection]  # unfiltered
    detection_time_ms: float


@dataclass(eq=False)
class ClassificationComplete:
    path: str
    names: dict[Box, Taxonomy]
    classification_time_ms: float


@dataclass(frozen=True)
class ImageError:
    path: str
    message: str


@dataclass(frozen=True)
class ClassifierError:
    message: str


@dataclass(frozen=True)
class CacheUpdated:
    paths: list[str]  # cached paths a request would be served for without inference


type Report = ImageLoaded | DetectionComplete | ClassificationComplete | ImageError | ClassifierError | CacheUpdated


class Browsing:
    """
    The shown image and its prefetch neighbours, and what they still need.
    Keeps their images and results in an ImageStore, which an Export shares.
    A failure is not retried until its image is shown again.
    """

    def __init__(self, store: ImageStore):
        self._store = store
        self._request: ShowRequest | None = None
        self._hints: list[str] = []  # prefetch paths, nearest first
        self._prefetched: set[str] = set()  # hints decoded since the last prefetch(), not decoded again when evicted
        self._delivered: set[str] = set()  # what was reported for the current request
        self._failed_paths: set[str] = set()  # paths that failed to decode, not retried until shown again
        self._detect_failed: set[str] = set()  # paths the detector failed on, not retried until shown again
        self._errors: list[Report] = []  # failures of the shown image, reported with the next reports()
        self._last_cached: list[str] = []  # the paths CacheUpdated reported last

    def show(self, request: ShowRequest) -> None:
        """
        Makes request the one to serve. Another path starts over: its earlier
        failures are retried and everything about it is reported again.
        Another threshold reports the names again, another exposure the image.
        """
        previous, self._request = self._request, request
        if previous is None or previous.path != request.path:
            self._store.pin(request.path)
            self._failed_paths.discard(request.path)
            self._detect_failed.discard(request.path)
            results = self._store.results(request.path)
            if results is not None:
                results.failed_boxes.clear()
            self._delivered.clear()
        else:
            if previous.detection_threshold != request.detection_threshold:
                self._delivered.discard(NAMES)
            if previous.exposure_correction != request.exposure_correction:
                self._delivered.discard(IMAGE)

    def prefetch(self, paths: list[str]) -> None:
        """
        Sets the images to decode, detect and classify ahead of time while
        idle, nearest first. Only as many as the image budget holds next to
        the shown image are prefetched, so a longer list costs nothing.
        """
        self._hints = list(paths)
        self._prefetched.clear()

    def is_wanted(self, job: DecodeJob | DisplayJob | DetectJob | ClassifyJob) -> bool:
        """Whether job is for the shown path or a prefetched one."""
        return job.path in self._wanted_paths()

    def on_detector_dropped(self) -> None:
        """Forgets the results and what failed with the detector."""
        self._store.clear_results()
        self._detect_failed.clear()
        # The image too, as the window may have replaced it by a message, e.g. a model that failed to load
        self._delivered.clear()

    def on_classifier_dropped(self) -> None:
        """Forgets the names the classifier gave."""
        self._store.clear_names()
        self._delivered.discard(NAMES)

    def clear(self) -> None:
        """Drops all decoded images, results and failures, and serves the current request from scratch."""
        self._store.clear()
        self._failed_paths.clear()
        self._detect_failed.clear()
        self._delivered.clear()

    def next_decode(self, models: Models) -> DecodeJob | DisplayJob | None:
        """Decodes the wanted images and builds their display arrays, the shown image first."""
        for path in self._wanted_paths():
            is_shown = self._is_shown(path)
            work = self._needs(path, models, as_shown=is_shown).image
            if work is Work.DECODE:
                if not is_shown:
                    # A hint evicted for lack of room is not decoded again, which would evict the next one, endlessly
                    if path in self._prefetched:
                        continue
                    self._prefetched.add(path)
                return DecodeJob(path, CancelToken())
            if work is Work.DISPLAY:
                return DisplayJob(self._store.image(path).image, self._exposure(), CancelToken())
        return None

    def next_inference(self, models: Models) -> DetectJob | ClassifyJob | None:
        """Detects and names the wanted images, the shown image first."""
        for path in self._wanted_paths():
            needs = self._needs(path, models)
            if needs.inference is Work.DETECT:
                return DetectJob(self._store.image(path).image, models.detector_id, CancelToken())
            if needs.inference is Work.CLASSIFY:
                return ClassifyJob(self._store.image(path).image, list(needs.boxes), models.classifier_id,
                                   CancelToken())
        return None

    def should_preempt(self, job: DetectJob | ClassifyJob | None, models: Models) -> bool:
        """
        Whether to stop naming another image, as the shown one is decoded and
        needs inference, so its boxes do not wait for a crowded neighbour. The
        job stops after its current batch of crops and keeps the names it got.
        A detect job is left to finish, as it cannot be interrupted and is short.
        """
        request = self._request
        return (isinstance(job, ClassifyJob) and request is not None and job.path != request.path
                and self._needs(request.path, models).inference in (Work.DETECT, Work.CLASSIFY))

    def on_decoded(self, job: DecodeJob, image: ImageObject) -> None:
        if not job.token.cancelled:
            self._store.put_image(job.path, image)

    def on_displayed(self, job: DisplayJob, display: np.ndarray) -> None:
        if not job.token.cancelled:
            self._store.put_display(job.image, display, job.exposure_correction)

    def on_decode_failed(self, job: DecodeJob | DisplayJob, message: str) -> None:
        if job.token.cancelled:
            return
        self._failed_paths.add(job.path)
        if self._is_shown(job.path):
            self._errors.append(ImageError(job.path, message))

    def on_detected(self, job: DetectJob, detections: list[Detection], detection_time_ms: float,
                    models: Models) -> None:
        # A job for a replaced model is stale. One for an older version of the file is stored with its image's
        # stamp, which tells it apart from the current version.
        if not job.token.cancelled and job.model_id == models.detector_id:
            self._store.put_detections(job.image, detections, detection_time_ms)

    def on_classified(self, job: ClassifyJob, names: dict[Box, Taxonomy], classification_time_ms: float,
                      models: Models) -> None:
        results = self._store.results(job.path)
        # Names of a cancelled job are kept: they are valid for the classifier that gave them
        if job.model_id == models.classifier_id and results is not None:
            results.add_names(names, classification_time_ms)

    def on_detect_failed(self, job: DetectJob, message: str, models: Models) -> None:
        if job.model_id != models.detector_id:
            return
        self._detect_failed.add(job.path)
        if self._is_shown(job.path):
            self._errors.append(ImageError(job.path, f"Error processing image: {message}"))

    def on_classify_failed(self, job: ClassifyJob, message: str, models: Models) -> None:
        results = self._store.results(job.path)
        if job.model_id != models.classifier_id or results is None:
            return
        results.failed_boxes.update(job.boxes)
        if self._is_shown(job.path):
            self._errors.append(ClassifierError(f"{os.path.basename(job.path)}: {message}"))

    def reports(self, models: Models) -> list[Report]:
        """
        What to tell the window, each once: the failures of the shown image,
        then its image, detections and names as they become ready, then the
        cached paths if they changed.
        """
        reports, self._errors = self._errors, []
        reports += self._ready(models)
        cached = self._cached_paths(models)
        if cached != self._last_cached:
            self._last_cached = cached
            reports.append(CacheUpdated(cached))
        return reports

    def _ready(self, models: Models) -> list[Report]:
        """What is ready for the current request and not reported yet, in order."""
        request = self._request
        if request is None:
            return []
        reports = []
        loaded = self._store.image(request.path)
        if IMAGE not in self._delivered:
            if loaded is None or loaded.display_exposure != request.exposure_correction:
                return reports
            self._delivered.add(IMAGE)
            reports.append(ImageLoaded(request.path, loaded.image, loaded.display))
            if not models.detector_state.is_loaded_or_loading and ERROR not in self._delivered:
                self._delivered.add(ERROR)
                reports.append(ImageError(request.path, "Model not loaded."))
        results = self._store.results(request.path)
        if results is None:
            return reports
        if DETECTIONS not in self._delivered:
            self._delivered.add(DETECTIONS)
            reports.append(DetectionComplete(request.path, results.detections, results.detection_time_ms))
        # Reported once no more names come. A classifier that failed to load still reports, without names, as the
        # window waits while one is selected.
        if (NAMES not in self._delivered and models.classifier_state is not ModelState.NONE
                and self._needs(request.path, models).inference is None):
            self._delivered.add(NAMES)
            reports.append(ClassificationComplete(request.path, dict(results.names), results.classification_time_ms))
        return reports

    def _cached_paths(self, models: Models) -> list[str]:
        """
        The paths a request would be served for without inference: image and
        detections cached and, with a classifier, every box at the current
        threshold named. A box the classifier failed on counts as unnamed,
        as a request would try it again. A display built with the other
        exposure counts, as the window highlights what is analyzed.
        """
        return [path for path in self._store.paths()
                if self._store.results(path) is not None and self._needs(path, models, retry_failures=True).settled]

    def _needs(self, path: str, models: Models, as_shown: bool = False, retry_failures: bool = False) -> Needs:
        """
        What path still needs, the one answer behind scheduling, preemption
        and what is reported. as_shown also asks for a display at the current
        exposure, as a hint keeps the exposure it was displayed with until it
        is shown, so toggling the exposure rebuilds the display of the shown
        image only. retry_failures counts what failed as still needed, as
        showing a path again tries it again.
        """
        loaded = self._store.image(path)
        if path in self._failed_paths and not retry_failures:
            image = None
        elif loaded is None:
            image = Work.DECODE
        elif loaded.display is None or (as_shown and loaded.display_exposure != self._exposure()):
            image = Work.DISPLAY
        else:
            image = None

        results = self._store.results(path)
        if models.detector_id is None:
            return Needs(image, Work.WAIT if models.detector_state.is_loaded_or_loading else None)
        if loaded is None:
            # Without a decode coming, the image failed to load
            return Needs(image, Work.WAIT if image is Work.DECODE else None)
        if results is None:
            detect = retry_failures or path not in self._detect_failed
            return Needs(image, Work.DETECT if detect else None)
        if models.classifier_id is not None:
            boxes = results.unnamed_boxes(self._threshold(), models.patterns, include_failed=retry_failures)
            if boxes:
                return Needs(image, Work.CLASSIFY, tuple(boxes))
        return Needs(image, Work.WAIT if models.classifier_state is ModelState.LOADING else None)

    def _wanted_paths(self) -> list[str]:
        """The shown path first, then the prefetch hints that fit in the image budget next to it."""
        paths = [] if self._request is None else [self._request.path]
        return paths + [path for path in self._hints[:self._store.room()] if path not in paths]

    def _is_shown(self, path: str) -> bool:
        return self._request is not None and path == self._request.path

    def _threshold(self) -> float:
        return self._request.detection_threshold if self._request is not None else 0.0

    def _exposure(self) -> bool:
        return self._request.exposure_correction if self._request is not None else False
