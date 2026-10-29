"""Tests for the byte bounded LruCache and the ImageResults kept per image.

The cache never looks into the stored values, so plain strings stand in for
the heavyweight payloads, sized by their length.
"""

import numpy as np
import pytest

from detectorist.cache import ImageResults, LruCache, image_cache_budget, results_cache_budget
from detectorist.structures import Detection, PackedMask
from detectorist.utils import FileStamp
from tests.fakes import TAXONOMY

STAMP = FileStamp("a.png", 1, 2)


def test_lru_evicts_least_recently_used_beyond_budget():
    cache = LruCache(10, len)
    cache.put("a", "xxxx")
    cache.put("b", "xxxx")

    cache.put("c", "xxxx")

    assert cache.keys() == ["b", "c"]
    assert cache.nbytes == 8


def test_lru_get_refreshes_recency():
    cache = LruCache(10, len)
    cache.put("a", "xxxx")
    cache.put("b", "xxxx")

    assert cache.get("a") == "xxxx"
    cache.put("c", "xxxx")

    assert cache.keys() == ["a", "c"]


def test_lru_peek_keeps_recency():
    cache = LruCache(10, len)
    cache.put("a", "xxxx")
    cache.put("b", "xxxx")

    assert cache.peek("a") == "xxxx"
    cache.put("c", "xxxx")

    assert cache.keys() == ["b", "c"]


def test_lru_never_evicts_the_pinned_key():
    cache = LruCache(10, len)
    cache.put("a", "xxxx")
    cache.pin("a")
    cache.put("b", "xxxx")

    cache.put("c", "xxxx")

    assert cache.keys() == ["a", "c"]


def test_lru_keeps_a_single_oversized_entry():
    cache = LruCache(10, len)
    cache.put("a", "xxxx")

    cache.put("b", "x" * 20)

    assert cache.keys() == ["b"]


def test_lru_pop_and_clear_update_the_size():
    cache = LruCache(10, len)
    cache.put("a", "xxxx")
    cache.put("b", "xx")

    assert cache.pop("a") == "xxxx"
    assert cache.nbytes == 2
    cache.clear()
    assert cache.nbytes == 0
    assert "b" not in cache


FISH = Detection((0, 0, 10, 10), 0.9, "Fish")
FAINT_FISH = Detection((20, 0, 10, 10), 0.3, "Fish")
CRAB = Detection((40, 0, 10, 10), 0.8, "Crab")
NAMED_FISH = Detection((60, 0, 10, 10), 0.7, "Fish")
FAILED_FISH = Detection((80, 0, 10, 10), 0.6, "Fish")


def test_unnamed_boxes_skips_named_failed_and_low_scoring():
    results = ImageResults(STAMP, [FISH, FAINT_FISH, CRAB, NAMED_FISH, FAILED_FISH], 1.0)
    results.names[NAMED_FISH.box] = TAXONOMY
    results.failed_boxes.add(FAILED_FISH.box)

    assert results.unnamed_boxes(0.5, ["Fish"]) == [FISH.box]
    assert results.unnamed_boxes(0.2, ["*"]) == [FISH.box, CRAB.box, FAINT_FISH.box]



def test_unnamed_boxes_counts_failed_boxes_if_asked_to():
    results = ImageResults(STAMP, [FISH, FAILED_FISH], 1.0)
    results.failed_boxes.add(FAILED_FISH.box)

    assert results.unnamed_boxes(0.5, ["Fish"], include_failed=True) == [FISH.box, FAILED_FISH.box]

def test_unnamed_boxes_honours_the_class_filter():
    results = ImageResults(STAMP, [FISH, CRAB], 1.0)

    assert results.unnamed_boxes(0.0, ["*"], class_filter="Crab") == [CRAB.box]


def test_results_size_counts_packed_masks():
    mask = PackedMask.from_mask(np.full((32, 32), 255, dtype=np.uint8))
    results = ImageResults(STAMP, [Detection((0, 0, 4, 4), 0.9, "Fish", mask), FISH], 1.0)

    assert results.nbytes() == mask.nbytes + 2 * 64


GB = 10**9


@pytest.mark.parametrize(("ram", "images", "results"), [
    (16 * GB, 4.8 * GB, 0.64 * GB),
    (8 * GB, 4 * GB, 0.32 * GB),  # images clamped up, so a small machine still prefetches neighbours
    (128 * GB, 38.4 * GB, 1 * GB),  # no upper limit for images, results clamped down
])
def test_cache_budgets_follow_the_ram(ram, images, results):
    assert image_cache_budget(ram) == int(images)
    assert results_cache_budget(ram) == int(results)
