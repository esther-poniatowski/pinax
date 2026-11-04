"""
Matching of each record work with the library.

A record states its own DOI, so the DOI route does not meet the cited DOIs that a page can hold;
the title of the item must still equal the title of the record, since an export can carry a wrong
DOI. A work without a matching DOI is matched by its normalized title, its year within the
tolerance, and its first author. The normalization folds case, so a title differing in case only
still matches. A candidate that one test refutes, or several candidates, leave the work to check.

Classes
-------
RecordMatcher
    Matching of record works with one library snapshot.
"""

from collections.abc import Sequence

from pinax.config import MatchingConfig
from pinax.errors import ConfigError
from pinax.library.model import Item, Library
from pinax.matching.model import Method, RecordMatch, Status
from pinax.matching.resolutions import Action, Resolutions
from pinax.records.works import RecordWork
from pinax.text import names_agree, words


def _title(text: str) -> str:
    """Title folded in case and accents, as `Record.normalized_title` folds it."""
    return " ".join(words(text))


class RecordMatcher:
    """
    Matching of record works with one library snapshot.

    Parameters
    ----------
    library : Library
        Library snapshot.
    config : MatchingConfig
        Year tolerance and surname prefix.
    resolutions : Resolutions
        Manual resolutions, of which the matcher reads those of record works.
    """

    def __init__(self, library: Library, config: MatchingConfig, resolutions: Resolutions) -> None:
        self._library = library
        self._config = config
        self._resolutions = resolutions
        self._titles: dict[str, list[str]] = {}
        for item in library.regular():
            title = _title(item.title)
            if title:
                self._titles.setdefault(title, []).append(item.key)

    def match_all(self, works: Sequence[RecordWork]) -> list[RecordMatch]:
        """Match every work, in order."""
        return [self.match(work) for work in works]

    def _require(self, key: str) -> Item:
        """Live item of a key, following merges; a missing item is a configuration error."""
        item = self._library.survivor(key)
        if item is None:
            raise ConfigError(f"item {key} is not in the library snapshot")
        return item

    def _outcome(
        self, work: RecordWork, status: Status, item: str = "", method: Method | None = None
    ) -> RecordMatch:
        """Match of a work, without a note."""
        return RecordMatch(work.identity, work.refs, status, item, method)

    def _by_doi(self, work: RecordWork, rejected: set[str], notes: list[str]) -> RecordMatch | None:
        """Only live item recording the DOI, confirmed by its title; None without such an item."""
        record = work.best
        if not record.doi:
            return None
        keys = [key for key in self._library.by_doi(record.doi) if key not in rejected]
        if not keys:
            return None
        if len(keys) > 1:
            notes.append(f"several items record the DOI: {", ".join(keys)}")
            return self._outcome(work, Status.CHECK, keys[0], Method.DOI)
        item = self._require(keys[0])
        if record.has_metadata and _title(item.title) != record.normalized_title:
            notes.append(f"{item.key} records the DOI under another title")
            return self._outcome(work, Status.CHECK, item.key, Method.DOI)
        return self._outcome(work, Status.MATCHED, item.key, Method.DOI)

    def _agrees(self, work: RecordWork, item: Item) -> bool:
        """Whether the year and the first author of the record do not refute an item."""
        record = work.best
        year, item_year = record.year, item.year
        if year is not None and item_year is not None:
            if abs(year - item_year) > self._config.year_tolerance:
                return False
        if not record.creators or not item.surnames:
            return True
        first = words(record.creators[0].last_name)
        names = {word for surname in item.surnames for word in words(surname)}
        prefix = self._config.surname_prefix
        return any(names_agree(a, b, prefix) for a in first for b in names)

    def _by_title(
        self, work: RecordWork, rejected: set[str], notes: list[str]
    ) -> RecordMatch | None:
        """Only live item with the same title, year and first author; None without a candidate."""
        title = work.best.normalized_title
        if not title:
            return None
        live = [self._library.survivor(key) for key in self._titles.get(title, [])]
        candidates = list(
            {item.key: item for item in live if item is not None and item.key not in rejected}
        )
        if not candidates:
            return None
        agreeing = [key for key in candidates if self._agrees(work, self._library.items[key])]
        if len(agreeing) == 1:
            return self._outcome(work, Status.MATCHED, agreeing[0], Method.TITLE)
        if agreeing:
            notes.append(f"several items have the title: {", ".join(agreeing)}")
        else:
            notes.append(f"{", ".join(candidates)} have the title, not the year or first author")
        return self._outcome(work, Status.CHECK, (agreeing or candidates)[0], Method.TITLE)

    def match(self, work: RecordWork) -> RecordMatch:
        """
        Match one work.

        Parameters
        ----------
        work : RecordWork
            Records sharing one identity.

        Returns
        -------
        RecordMatch
            Outcome; a work whose records disagree, or whose candidate one test refutes, has
            status `CHECK` until a resolution decides. A rejection without item confirms that no
            item holds the work.

        Raises
        ------
        ConfigError
            If a resolution names an item absent from the library, or accepts a work that no route
            matches.
        """
        resolution = self._resolutions.record(work.identity)
        notes: list[str] = list(work.disagreements)
        rejected: set[str] = set()
        if resolution and resolution.action in (Action.ASSIGN, Action.PREPRINT_OF):
            item = self._require(resolution.item).key
            status = (
                Status.PREPRINT_OF if resolution.action is Action.PREPRINT_OF else Status.MATCHED
            )
            note = "; ".join(filter(None, [*notes, resolution.note]))
            return RecordMatch(work.identity, work.refs, status, item, Method.RESOLUTION, note)
        if resolution and resolution.action is Action.REJECT:
            if not resolution.item:
                note = "; ".join(filter(None, ["rejected by resolution", resolution.note]))
                return RecordMatch(work.identity, work.refs, Status.ABSENT, note=note)
            rejected.add(self._require(resolution.item).key)
            notes.append(f"{resolution.item} rejected by resolution")
        found = self._by_doi(work, rejected, notes) or self._by_title(work, rejected, notes)
        if work.disagreements:
            # Records that disagree wait for a decision, even when no item matches them.
            found = self._outcome(
                work, Status.CHECK, found.item if found else "", found.method if found else None
            )
        if resolution and resolution.action is Action.ACCEPT:
            if found is None or not found.item:
                raise ConfigError(f"resolution accepts {work.identity}, which no route matches")
            notes.append("accepted by resolution")
            found = self._outcome(work, Status.MATCHED, found.item, found.method)
        if resolution and resolution.note:
            notes.append(resolution.note)
        if found is None:
            return RecordMatch(work.identity, work.refs, Status.ABSENT, note="; ".join(notes))
        return RecordMatch(
            work.identity, work.refs, found.status, found.item, found.method, "; ".join(notes)
        )
