"""Tests for species list files."""

import pytest

from detectorist.species_list_file import Matches, format_list, match, parse
from detectorist.structures import Taxon

TAXA = [
    Taxon("Andrena_fulva", "Andrena", "Andrenidae"),
    Taxon("Bombus_lapidarius", "Bombus", "Apidae"),
    Taxon("Bombus_terrestris", "Bombus", "Apidae"),
    Taxon("Osmia_bicornis", "Osmia", "Megachilidae"),
]


def test_parse_skips_comments_blank_lines_and_repeats():
    text = "# Survey 2026\n\nBombus terrestris  # common\n  Osmia\tbicornis\nBombus terrestris\n#\n"

    assert parse(text) == ["Bombus terrestris", "Osmia bicornis"]


def test_parse_reads_the_first_column_of_a_csv_row():
    assert parse("Bombus terrestris,Linnaeus 1758,Apidae\n") == ["Bombus terrestris"]


@pytest.mark.parametrize(("entry", "species"), [
    ("Bombus terrestris", ["Bombus_terrestris"]),
    ("BOMBUS TERRESTRIS", ["Bombus_terrestris"]),
    ("Bombus_terrestris", ["Bombus_terrestris"]),
    ("bombus", ["Bombus_lapidarius", "Bombus_terrestris"]),
    ("Bombus *", ["Bombus_lapidarius", "Bombus_terrestris"]),
    ("APIDAE", ["Bombus_lapidarius", "Bombus_terrestris"]),
    ("*idae", [taxon.species for taxon in TAXA]),
    ("* bicorn?s", ["Osmia_bicornis"]),
])
def test_an_entry_selects_species_by_name_genus_family_or_glob(entry, species):
    matches = match([entry], TAXA)

    assert matches == Matches(tuple(species), ())


@pytest.mark.parametrize("entry", [
    "Apidae Bombus terrestris",
    "Bombus terrestris (Linnaeus, 1758)",
    "Bombus terrestris audax",
    "Bombus spp.",
    "Apidae Bombus",
])
def test_a_line_in_any_other_form_is_reported_rather_than_guessed_at(entry):
    assert match([entry], TAXA) == Matches((), (entry,))


def test_an_unknown_species_is_reported_rather_than_widened_to_its_genus():
    assert match(["Bombus hortorum", "Vespa *"], TAXA) == Matches((), ("Bombus hortorum", "Vespa *"))


def test_species_selected_twice_are_listed_once_in_taxa_order():
    assert match(["Osmia bicornis", "Bombus", "Bombus terrestris"], TAXA).species == (
        "Bombus_lapidarius", "Bombus_terrestris", "Osmia_bicornis")


def test_a_formatted_list_reads_back_to_the_same_species():
    species = ["Osmia_bicornis", "Bombus_terrestris"]
    text = format_list(species, ["Species list for Bees", "Exported on 2026-11-27"])

    assert text == ("# Species list for Bees\n# Exported on 2026-11-27\n\n"
                    "Bombus terrestris\nOsmia bicornis\n")
    assert match(parse(text), TAXA).species == ("Bombus_terrestris", "Osmia_bicornis")
