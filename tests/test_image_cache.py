"""Tests for the ImageCache LRU behaviour.

The cache never touches the stored objects, so plain strings stand in for
the heavyweight CacheEntry payloads.
"""

from detectorist.image_cache import ImageCache


def test_put_get_roundtrip():
    cache = ImageCache(max_entries=2)
    cache.put("a", "entry-a")
    assert cache.get("a") == "entry-a"
    assert cache.get("missing") is None


def test_eviction_drops_least_recently_used():
    cache = ImageCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert "a" not in cache
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_get_refreshes_recency():
    cache = ImageCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)  # evicts b, since a was just used
    assert "a" in cache
    assert "b" not in cache


def test_put_of_existing_key_updates_and_refreshes():
    cache = ImageCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)  # evicts b, since a was just re-put
    assert cache.get("a") == 10
    assert "b" not in cache


def test_contains_does_not_change_recency():
    cache = ImageCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" in cache
    cache.put("c", 3)  # a is still the least recently used and gets evicted
    assert "a" not in cache


def test_clear():
    cache = ImageCache(max_entries=2)
    cache.put("a", 1)
    cache.clear()
    assert "a" not in cache
    assert cache.get("a") is None
