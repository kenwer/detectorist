"""
The caches the Pipeline keeps: decoded images and the results of inference.
Qt-free so they can be unit-tested headless.

Pixels are large and cheap to recreate, results are small and expensive, so
each gets its own LruCache with its own budget. Both are keyed by path and
never reference each other, so evicting from one cannot leave the other
inconsistent. The FileStamp of each entry tells whether the file changed
since.
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from .classifier import detections_to_classify
from .image_object import ImageObject
from .structures import Box, Detection, Taxonomy
from .utils import FileStamp

GB = 10**9


def image_cache_budget(ram_bytes: int) -> int:
    """
    30% of the RAM for decoded images, but at least 4 GB. On a 16 GB machine
    that is 4.8 GB, about 16 decoded 33 MP 16-bit images (196 MB) with their
    8-bit display arrays (98 MB). There is no upper limit: prefetching is
    bounded by the neighbours the app offers, so the rest keeps recently
    viewed images for going back.
    """
    return max(ram_bytes * 30 // 100, 4 * GB)


def results_cache_budget(ram_bytes: int) -> int:
    """
    4% of the RAM for inference results, but at least 300 MB and at most
    1 GB. Packed masks take about 50 KB per segmented image, so 640 MB on a
    16 GB machine hold about 13k images.
    """
    return min(max(ram_bytes * 4 // 100, 300 * 10**6), 1 * GB)

# Rough per detection overhead besides its mask (box, score, class name, tuple)
DETECTION_BYTES = 64


class LruCache[K, V]:
    """
    A least recently used cache bounded by the bytes size_of reports for
    its values. One pinned key is never evicted, e.g. the image on screen.
    The entry just put is never evicted either, so one entry larger than
    the budget is kept alone rather than thrown away right after the work.
    """

    def __init__(self, budget_bytes: int, size_of: Callable[[V], int]):
        self._budget_bytes = budget_bytes
        self._size_of = size_of
        self._entries: dict[K, tuple[V, int]] = {}  # dicts keep insertion order, the first key is the oldest
        self._nbytes = 0
        self._pinned: K | None = None

    def get(self, key: K) -> V | None:
        """Returns the value for key and marks it as most recently used."""
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        self._entries[key] = entry
        return entry[0]

    def peek(self, key: K) -> V | None:
        """Returns the value for key without changing its recency."""
        entry = self._entries.get(key)
        return None if entry is None else entry[0]

    def put(self, key: K, value: V) -> None:
        """Stores value as most recently used, then evicts the oldest entries beyond the budget."""
        self.pop(key)
        size = self._size_of(value)
        self._entries[key] = (value, size)
        self._nbytes += size
        for old_key in list(self._entries):
            if self._nbytes <= self._budget_bytes:
                break
            if old_key not in (key, self._pinned):
                self.pop(old_key)

    def pop(self, key: K) -> V | None:
        """Removes and returns the value for key."""
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        self._nbytes -= entry[1]
        return entry[0]

    def pin(self, key: K | None) -> None:
        """Protects key from eviction, replacing the previous pin. None unpins."""
        self._pinned = key

    def __contains__(self, key: K) -> bool:
        return key in self._entries

    def keys(self) -> list[K]:
        """The keys from least to most recently used."""
        return list(self._entries)

    def items(self) -> list[tuple[K, V]]:
        """The (key, value) pairs from least to most recently used."""
        return [(key, value) for key, (value, _) in self._entries.items()]

    def clear(self) -> None:
        self._entries.clear()
        self._nbytes = 0

    @property
    def nbytes(self) -> int:
        return self._nbytes


@dataclass
class LoadedImage:
    """A decoded image and, once built, its display array."""
    image: ImageObject
    display: np.ndarray | None = None  # 8-bit RGB, ready for a QImage, None until built
    display_exposure: bool | None = None  # whether display is exposure corrected, None until built

    @property
    def stamp(self) -> FileStamp:
        return self.image.stamp

    def nbytes(self) -> int:
        return self.image.image_data.nbytes + (self.display.nbytes if self.display is not None else 0)


@dataclass
class ImageResults:
    """What inference found in one image, valid for the file version in stamp."""
    stamp: FileStamp
    detections: list[Detection]  # unfiltered, as Detector.detect returns them
    detection_time_ms: float
    names: dict[Box, Taxonomy] = field(default_factory=dict)  # what the classifier said, per box
    classification_time_ms: float = 0.0  # summed over the runs that filled names
    failed_boxes: set[Box] = field(default_factory=set)  # boxes the classifier failed on, not retried until asked again

    def unnamed_boxes(self, threshold: float, patterns: Sequence[str], class_filter: str | None = None,
                      include_failed: bool = False) -> list[Box]:
        """
        The boxes still to name: detections at or above threshold whose class
        the classifier names (and is class_filter, if given), highest score
        first, without a name and, unless include_failed, not failed before.
        """
        return [d.box for d in detections_to_classify(self.detections, threshold, patterns)
                if (class_filter is None or d.class_name == class_filter)
                and d.box not in self.names and (include_failed or d.box not in self.failed_boxes)]

    def add_names(self, names: dict[Box, Taxonomy], classification_time_ms: float) -> None:
        """Keeps what one run of the classifier said, adding its time to the others."""
        self.names.update(names)
        self.classification_time_ms += classification_time_ms

    def clear_names(self) -> None:
        """Forgets what a classifier said, e.g. because another one was loaded."""
        self.names.clear()
        self.failed_boxes.clear()
        self.classification_time_ms = 0.0

    def nbytes(self) -> int:
        return sum((d.mask.nbytes if d.mask is not None else 0) + DETECTION_BYTES for d in self.detections)


class ImageStore:
    """
    The decoded images and the results of inference the Pipeline keeps, in
    two LruCaches of their own budgets. Results are handed out only for the
    version of the file decoded last, so a file rewritten since is detected
    again. The image shown is pinned, so it is never evicted.
    """

    def __init__(self, image_budget_bytes: int, results_budget_bytes: int):
        self._image_budget = image_budget_bytes
        self._images: LruCache[str, LoadedImage] = LruCache(image_budget_bytes, LoadedImage.nbytes)
        self._results: LruCache[str, ImageResults] = LruCache(results_budget_bytes, ImageResults.nbytes)
        self._entry_bytes: int | None = None  # size of the image displayed last with its display array, the estimate for the others

    def image(self, path: str) -> LoadedImage | None:
        return self._images.peek(path)

    def results(self, path: str) -> ImageResults | None:
        """The results for path, unless they belong to another version of the file than the image cached."""
        results = self._results.peek(path)
        loaded = self._images.peek(path)
        if results is None or (loaded is not None and results.stamp != loaded.stamp):
            return None
        return results

    def results_for(self, image: ImageObject) -> ImageResults | None:
        """The results for image, if they belong to its version of the file."""
        results = self._results.peek(image.image_path)
        return results if results is not None and results.stamp == image.stamp else None

    def paths(self) -> list[str]:
        """The paths of the images cached, from least to most recently used."""
        return self._images.keys()

    def pin(self, path: str) -> None:
        """Protects the image at path from eviction, e.g. the one shown, and marks it as most recently used."""
        self._images.get(path)
        self._images.pin(path)

    def room(self) -> int:
        """
        How many more images fit next to the pinned one, estimating each at
        the size of the image displayed last. 0 before the first is displayed,
        as the size is unknown.
        """
        if not self._entry_bytes:
            return 0
        return max(self._image_budget // self._entry_bytes - 1, 0)

    def put_image(self, path: str, image: ImageObject) -> None:
        """Keeps a decoded image, dropping the results of another version of the file."""
        results = self._results.peek(path)
        if results is not None and results.stamp != image.stamp:
            self._results.pop(path)
        self._images.put(path, LoadedImage(image))

    def put_display(self, image: ImageObject, display: np.ndarray, exposure_correction: bool) -> None:
        """Keeps the display array built for image, unless image is no longer the one cached."""
        loaded = self._images.peek(image.image_path)
        if loaded is None or loaded.image is not image:
            return
        loaded.display = display
        loaded.display_exposure = exposure_correction
        # Put again, as the cache sized the entry without its display
        self._images.put(image.image_path, loaded)
        self._entry_bytes = loaded.nbytes()

    def put_detections(self, image: ImageObject, detections: list[Detection], detection_time_ms: float) -> None:
        """Keeps what the detector found in image, replacing any earlier results with their names."""
        self._results.put(image.image_path, ImageResults(image.stamp, detections, detection_time_ms))

    def clear_names(self) -> None:
        """Forgets what the classifier said about every image, e.g. because another one was loaded."""
        for _, results in self._results.items():
            results.clear_names()

    def clear_results(self) -> None:
        """Forgets all results, e.g. because another detector was loaded."""
        self._results.clear()

    def clear(self) -> None:
        self._images.clear()
        self._results.clear()
