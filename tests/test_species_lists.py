"""Tests for SpeciesLists, the species list of each classifier kept in the settings."""

import pytest

from detectorist.species_lists import SpeciesLists

KNOWN = ["Amphiprion_clarkii", "Amphiprion_ocellaris", "Chromis_viridis"]


@pytest.fixture
def lists(settings) -> SpeciesLists:
    return SpeciesLists(settings, {"fish-v0.onnx": "fish-v1.onnx"}.get)


def test_a_list_is_kept_sorted_and_removing_it_forgets_it_was_off(lists, settings):
    lists.set("fish.onnx", ["Chromis_viridis", "Amphiprion_ocellaris"], on=True)
    lists.set_on("fish.onnx", False)

    assert settings.classification_species_lists == {
        "fish.onnx": {"species": ["Amphiprion_ocellaris", "Chromis_viridis"], "on": False}}
    assert lists.applied("fish.onnx") == []

    lists.set("fish.onnx", [], on=True)

    assert settings.classification_species_lists is None
    assert lists.is_on("fish.onnx")


def test_the_list_of_a_superseded_model_moves_over_with_its_switch(lists, settings):
    lists.set("fish-v0.onnx", ["Amphiprion_ocellaris"], on=True)
    lists.set_on("fish-v0.onnx", False)

    lists.adopt_superseded("fish-v1.onnx")

    assert settings.classification_species_lists == {"fish-v1.onnx": {"species": ["Amphiprion_ocellaris"], "on": False}}


def test_a_successor_keeps_its_own_list(lists):
    lists.set("fish-v0.onnx", ["Amphiprion_ocellaris"], on=True)
    lists.set("fish-v1.onnx", ["Chromis_viridis"], on=True)

    lists.adopt_superseded("fish-v1.onnx")

    assert lists.get("fish-v1.onnx") == ["Chromis_viridis"]
    assert lists.get("fish-v0.onnx") == ["Amphiprion_ocellaris"]


@pytest.mark.parametrize(("species", "kept", "unknown"), [
    (["Amphiprion_ocellaris", "Scarus_iseri"], ["Amphiprion_ocellaris"], ["Scarus_iseri"]),
    (["Scarus_iseri"], [], ["Scarus_iseri"]),
    (KNOWN, KNOWN, []),
    (["Chromis_viridis"], ["Chromis_viridis"], []),
])
def test_fit_to_drops_unknown_species(lists, species, kept, unknown):
    lists.set("fish.onnx", species, on=False)

    assert lists.fit_to("fish.onnx", KNOWN) == unknown
    assert lists.get("fish.onnx") == kept
    assert lists.is_on("fish.onnx") == (not kept)


def test_stored_lists_of_another_shape_are_ignored(lists, settings):
    settings.classification_species_lists = {"old.onnx": ["Chromis_viridis"]}

    assert lists.get("old.onnx") == []
    assert lists.is_on("old.onnx")

    lists.set("fish.onnx", ["Chromis_viridis"], on=True)

    assert settings.classification_species_lists == {"fish.onnx": {"species": ["Chromis_viridis"], "on": True}}
