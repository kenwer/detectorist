"""Tests for the ImageCache LRU behaviour and PrefetchPlanner direction logic.

The cache never touches the stored objects, so plain strings stand in for
the heavyweight CacheEntry payloads.
"""

from detectorist.image_cache import ImageCache, PrefetchPlanner


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


def test_paths_reflects_current_entries_oldest_first():
    cache = ImageCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.paths() == ["a", "b"]
    cache.put("c", 3)  # evicts a
    assert cache.paths() == ["b", "c"]


PATHS = [str(i) for i in range(20)]


def test_first_selection_has_no_direction_yet():
    planner = PrefetchPlanner()
    assert planner.hints(PATHS, "10") == ["11", "9", "12", "8"]


def test_continuing_forward_gives_3_ahead_1_behind():
    planner = PrefetchPlanner()
    planner.hints(PATHS, "10")
    planner.hints(PATHS, "11")
    assert planner.hints(PATHS, "12") == ["11", "13", "14", "15"]


def test_continuing_backward_gives_3_ahead_1_behind():
    planner = PrefetchPlanner()
    planner.hints(PATHS, "12")
    planner.hints(PATHS, "11")
    assert planner.hints(PATHS, "10") == ["11", "9", "8", "7"]


def test_single_step_reversal_after_forward_is_a_probe():
    planner = PrefetchPlanner()
    planner.hints(PATHS, "10")
    planner.hints(PATHS, "11")  # forward
    planner.hints(PATHS, "12")  # forward again
    # One step back: protect the 2 nearest forward images, fetch 2 behind.
    assert planner.hints(PATHS, "11") == ["12", "13", "10", "9"]


def test_second_consecutive_reversal_escalates_to_3_ahead():
    planner = PrefetchPlanner()
    planner.hints(PATHS, "10")
    planner.hints(PATHS, "11")  # forward
    planner.hints(PATHS, "12")  # forward again
    planner.hints(PATHS, "11")  # probe: first step back
    # A second consecutive step backward confirms the reversal.
    assert planner.hints(PATHS, "10") == ["11", "9", "8", "7"]


def test_jump_resets_direction_so_next_step_is_not_a_probe():
    planner = PrefetchPlanner()
    planner.hints(PATHS, "10")
    planner.hints(PATHS, "11")  # forward, establishes direction
    # A non-adjacent selection is a jump: falls back to the symmetric shape.
    assert planner.hints(PATHS, "15") == ["16", "14", "17", "13"]
    # The next single step is treated as fresh, not a reversal probe.
    assert planner.hints(PATHS, "16") == ["15", "17", "18", "19"]


def test_reset_clears_tracked_direction():
    planner = PrefetchPlanner()
    planner.hints(PATHS, "10")
    planner.hints(PATHS, "11")  # forward, establishes direction and previous path
    planner.reset()
    # With state cleared, even an adjacent step falls back to the no-direction shape.
    assert planner.hints(PATHS, "12") == ["13", "11", "14", "10"]
