"""Species list files: plain text, one name per line, for import and export.

A line names a species as genus and epithet ("Bombus terrestris"), or a
genus or family as a single word ("Bombus", "Apidae"). Names match ignoring
case, "_" stands for a space as in the model's "Bombus_terrestris", and a
shell-style glob matches several ("Bombus *", "*idae"). Everything after "#"
is a comment, only the first column of a CSV row is read, and blank lines are
skipped. A line matching no species, such as one with authors or a family
before the genus, is reported, not guessed at. Qt-free so it can be tested
headless.
"""

import fnmatch
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .structures import Taxon


@dataclass(frozen=True)
class Matches:
    """The species a species list file selects, and the entries selecting none."""
    species: tuple[str, ...]  # In the order of the taxa matched against, each once
    unmatched: tuple[str, ...]  # Typos and names the classifier does not know


def parse(text: str) -> list[str]:
    """
    The entries of a species list file: the first column of its lines
    without comments, trimmed, with runs of whitespace as one space, without
    blank lines and repeats.
    """
    lines = (" ".join(line.partition("#")[0].partition(",")[0].split()) for line in text.splitlines())
    return list(dict.fromkeys(filter(None, lines)))


def _key(name: str) -> str:
    """A name or glob in the form names are compared in: lowercase, with spaces as "_" as in the model's names."""
    return name.replace(" ", "_").lower()


def match(entries: Iterable[str], taxa: Sequence[Taxon]) -> Matches:
    """The species the entries select: those whose own name, genus or family an entry matches."""
    keyed = [(taxon.species, (_key(taxon.species), _key(taxon.genus), _key(taxon.family))) for taxon in taxa]
    selected: set[str] = set()
    unmatched: list[str] = []
    for entry in entries:
        pattern = _key(entry)
        hits = {species for species, keys in keyed if any(fnmatch.fnmatchcase(key, pattern) for key in keys)}
        if not hits:
            unmatched.append(entry)
        selected |= hits
    return Matches(tuple(taxon.species for taxon in taxa if taxon.species in selected), tuple(unmatched))


def format_list(species: Iterable[str], header: Sequence[str] = ()) -> str:
    """
    A species list file of the given species, sorted and in the binomial
    form people write ("Bombus terrestris"), after the header lines as
    comments.
    """
    lines = [f"# {line}" for line in header]
    if lines:
        lines.append("")
    lines += sorted(name.replace("_", " ") for name in species)
    return "\n".join(lines) + "\n"
