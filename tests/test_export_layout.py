import pytest

from detectorist.export_layout import describe_export, safe_name, taxon_prefix
from detectorist.structures import RankedName

FULL = [RankedName("Pomacentridae", 0.99), RankedName("Amphiprion", 0.97), RankedName("Amphiprion_ocellaris", 0.9)]


@pytest.mark.parametrize(("has_classifier", "crop", "text"), [
    (True, True, "processed/, named by taxon, cropped"),
    (False, True, "processed/, named by class, cropped"),
    (True, False, "processed/, named by taxon, not cropped"),
])
def test_describe_export(has_classifier, crop, text):
    assert describe_export(has_classifier, crop) == text


@pytest.mark.parametrize("name, safe", [("Amphiprion_sp.", "Amphiprion_sp"), ('a:b*c?"<>|', "a_b_c_____"), ("ok", "ok")])
def test_safe_name_replaces_characters_windows_rejects(name, safe):
    assert safe_name(name) == safe


def test_taxon_prefix_makes_species_names_safe():
    odd = [RankedName("Fam:x", 1.0), RankedName("Gen", 1.0), RankedName("Gen_sp.", 1.0)]
    assert taxon_prefix(odd) == "Fam_x_Gen_sp"


@pytest.mark.parametrize(("ranks", "prefix"), [
    (FULL, "Pomacentridae_Amphiprion_ocellaris"),
    (FULL[:2], "Pomacentridae_Amphiprion_unidentified"),
    (FULL[:1], "Pomacentridae_unidentified"),
    ([], "unidentified"),
])
def test_taxon_prefix_names_the_identified_ranks_then_unidentified(ranks, prefix):
    assert taxon_prefix(ranks) == prefix


def test_taxon_prefix_makes_names_safe_for_windows():
    assert taxon_prefix([RankedName("Fam:ily", 1.0)]) == "Fam_ily_unidentified"
