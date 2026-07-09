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


class PrefetchPlanner:
    """
    Tracks navigation direction across image selections and decides which
    paths to prefetch next. Owned by the GUI thread (DetectoristApp) and
    never shared with ImageCache's worker-owned instance: this is why it is
    a separate class rather than state on ImageCache, despite living in the
    same module.

    A single step continuing the established direction of travel prefetches
    3 images ahead (protecting the from-image so it survives the upcoming
    evictions), giving 3 instant steps ahead and 1 instant step back. A
    single step that reverses the previous direction is treated as a probe:
    it only prefetches 2 in the new direction and protects the 2 nearest
    images in the old direction, so a quick bounce back stays instant. A
    second consecutive step in that new direction confirms the reversal and
    escalates back to the full 3-ahead prefetch.

    Falls back to 2 ahead and 2 behind (n+1, n-1, n+2, n-2) for the first
    selection or a jump, and resets the tracked direction.
    """

    def __init__(self) -> None:
        self._previous_path: str | None = None
        self._last_direction: str | None = None

    def reset(self) -> None:
        """Call when the image list changes (folder load) to drop stale history."""
        self._previous_path = None
        self._last_direction = None

    def hints(self, paths: list[str], current_path: str) -> list[str]:
        """Returns paths to decode ahead of time for current_path within paths."""
        try:
            row = paths.index(current_path)
        except ValueError:
            self._previous_path = current_path
            return []

        prev_row = None
        if self._previous_path is not None:
            try:
                prev_row = paths.index(self._previous_path)
            except ValueError:
                prev_row = None

        self._previous_path = current_path

        if prev_row is not None and abs(row - prev_row) == 1:
            direction = "forward" if row > prev_row else "backward"
            confirmed = self._last_direction is None or self._last_direction == direction
            self._last_direction = direction

            if direction == "forward":
                if confirmed:
                    # Promote the from-image first so it survives the forward loads.
                    return [paths[prev_row]] + paths[row + 1:row + 4]
                # Probe: protect the 2 nearest images behind, prefetch 2 ahead.
                behind = [paths[i] for i in (prev_row, prev_row - 1) if 0 <= i < len(paths)]
                return behind + paths[row + 1:row + 3]
            else:
                if confirmed:
                    # Same pattern as forward: protect the from-image first, then
                    # prefetch 3 in the direction of travel.
                    return [paths[prev_row]] + list(reversed(paths[max(0, row - 3):row]))
                # Probe: protect the 2 nearest images ahead, prefetch 2 behind.
                ahead = [paths[i] for i in (prev_row, prev_row + 1) if 0 <= i < len(paths)]
                return ahead + list(reversed(paths[max(0, row - 2):row]))

        # No clear direction: nearest 2 in each direction, alternating so the
        # closest neighbors are always decoded first.
        self._last_direction = None
        return [paths[i] for i in [row + 1, row - 1, row + 2, row - 2]
                if 0 <= i < len(paths)]
