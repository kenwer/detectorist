"""Pure naming rules for the files an export writes.

Qt-free, so the batch export and the crop panel summary share one rule. Ranks
are counted 1 family, 2 genus, 3 species.
"""

from collections.abc import Sequence

from .structures import RankedName

RANK_COUNT = 3  # family, genus, species
UNIDENTIFIED = "unidentified"  # stands in for the ranks below the taxon confidence
NO_DETECTION = "no-detection"  # prefix of an image without detections

_UNSAFE_CHARS = str.maketrans(dict.fromkeys('<>:"/\\|?*', "_"))


def safe_name(name: str) -> str:
    """Make a class or taxon name usable in a file name on Windows."""
    return name.translate(_UNSAFE_CHARS).rstrip(". ") or "_"


def taxon_prefix(ranks: Sequence[RankedName]) -> str:
    """
    The file name prefix of a classified detection: its identified ranks
    (see identified_ranks), then "unidentified" for the ranks it missed,
    like "Pomacentridae_Amphiprion_unidentified".
    """
    names = [r.name for r in ranks]
    # The model names species Genus_species, so the genus is already in the species name
    if len(names) == RANK_COUNT:
        return f"{safe_name(names[0])}_{safe_name(names[2])}"
    return "_".join([*(safe_name(n) for n in names), UNIDENTIFIED])


def describe_export(has_classifier: bool, crop: bool) -> str:
    """The one-line summary of the export shown in the crop panel."""
    named = "named by taxon" if has_classifier else "named by class"
    return f"processed/, {named}, {'cropped' if crop else 'not cropped'}"
