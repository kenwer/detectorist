"""The species list of each classifier, kept in the settings."""

from collections.abc import Callable, Collection, Sequence

from .settings import Settings


class SpeciesLists:
    """
    The species list of each classifier, keyed by its model file name, and
    whether it is switched on. A classifier without a list, or with its list
    switched off, names any species. Removing a list forgets its switch.
    """

    def __init__(self, settings: Settings, successor_of: Callable[[str], str | None]):
        """
        Args:
            settings: Where the lists are kept.
            successor_of: The model file that supersedes a given one, or None.
        """
        self._settings = settings
        self._successor_of = successor_of

    def _lists(self) -> dict[str, dict]:
        return dict(self._settings.classification_species_lists or {})

    def _save(self, lists: dict[str, dict]) -> None:
        self._settings.classification_species_lists = lists or None

    def get(self, filename: str) -> list[str]:
        """The species list of a classifier, empty for none."""
        return list(self._lists().get(filename, {}).get("species", []))

    def set(self, filename: str, species: Collection[str], on: bool) -> None:
        """Replaces the species list of a classifier and its switch, removing both for no species."""
        lists = self._lists()
        if species:
            lists[filename] = {"species": sorted(species), "on": on}
        else:
            lists.pop(filename, None)
        self._save(lists)

    def is_on(self, filename: str) -> bool:
        """Whether a classifier's species list is switched on, also while it has none."""
        return self._lists().get(filename, {}).get("on", True)

    def set_on(self, filename: str, on: bool) -> None:
        """Switches a classifier's species list on or off, keeping the list."""
        self.set(filename, self.get(filename), on)

    def applied(self, filename: str) -> list[str]:
        """The species a classifier names from, empty for any species."""
        return self.get(filename) if self.is_on(filename) else []

    def adopt_superseded(self, filename: str) -> None:
        """
        Moves the list of a model that filename supersedes over to it, as the
        model selection follows an update. A list of its own is kept.
        """
        lists = self._lists()
        if filename in lists:
            return
        superseded = next((name for name in lists if self._successor_of(name) == filename), None)
        if superseded is not None:
            lists[filename] = lists.pop(superseded)
            self._save(lists)

    def fit_to(self, filename: str, known: Sequence[str]) -> list[str]:
        """
        Removes the species a classifier does not know from its list.
        Returns those removed.
        """
        species = self.get(filename)
        known = frozenset(known)
        unknown = [name for name in species if name not in known]
        if unknown:
            self.set(filename, [name for name in species if name in known], self.is_on(filename))
        return unknown
