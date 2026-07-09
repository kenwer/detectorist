"""LRU cache for viewed images and their detection results.

Lets the DetectionWorker serve a re-selected image without decoding or
running inference again, and gives prefetched images a place to wait.
Qt-free so it can be unit-tested headless.
"""

from dataclasses import dataclass

from .image_object import ImageObject


@dataclass
class CacheEntry:
    """Everything the worker produces for one image."""

    image: ImageObject
    results: list  # unfiltered detections from Detector.detect
    detection_time_ms: float


class ImageCache:
    """
    A small LRU cache keyed by image path. Detection results depend only on
    the image file and the loaded model, so entries stay valid until the
    model changes or the files on disk may have (callers clear it then).

    The default capacity of 5 keeps 3 images ahead in the travel direction and
    1 image behind alongside the current image, so three consecutive steps in
    the browsing direction are served without decoding. Each decoded 33 MP
    16-bit image occupies roughly 200 MB, so the capacity is kept small.
    """

    def __init__(self, max_entries: int = 5):
        self._max_entries = max_entries
        # dicts preserve insertion order; the first key is the least recently used
        self._entries: dict[str, CacheEntry] = {}

    def get(self, path: str) -> CacheEntry | None:
        """Returns the entry for path and marks it as most recently used."""
        entry = self._entries.get(path)
        if entry is not None:
            self._entries[path] = self._entries.pop(path)
        return entry

    def put(self, path: str, entry: CacheEntry) -> None:
        """Stores an entry as most recently used, evicting the oldest if full."""
        self._entries.pop(path, None)
        self._entries[path] = entry
        if len(self._entries) > self._max_entries:
            oldest = next(iter(self._entries))
            del self._entries[oldest]

    def __contains__(self, path: str) -> bool:
        """Membership test without changing recency."""
        return path in self._entries

    def paths(self) -> list[str]:
        """Returns the paths of all currently cached entries."""
        return list(self._entries.keys())

    def clear(self) -> None:
        """Drops all entries."""
        self._entries.clear()
