"""
Matching of each content of the inventory with the library.

For each content, the matcher applies, in order:

1. a resolution that assigns the content, which decides alone;
2. the routes, in order: same stored file, DOI, file name. A same-file candidate is identical by
   construction; any other candidate is confirmed by its title, and a rejected candidate passes the
   content to the next route;
3. the reverse search, for a content still unmatched: an item is confirmed only when its title
   opens the first page;
4. a resolution that accepts a candidate left to check.

Classes
-------
Matcher
    Matching of contents with one library snapshot.
"""

from collections.abc import Mapping, Sequence

from pinax.config import MatchingConfig
from pinax.errors import ConfigError
from pinax.library.model import Item, Library
from pinax.matching.candidates import CandidateSource, DoiSource, NameSource, SameFileSource
from pinax.matching.confirm import TitleConfirmer, TitleIndex
from pinax.matching.model import Candidate, Match, Method, Status, Verdict
from pinax.matching.resolutions import Action, Resolution, Resolutions
from pinax.sources.inventory import Content, Inventory

MAX_CITED_NOTED = 5
"""Number of cited items listed in the note of a match, enough to judge a reverse search."""


class Matcher:
    """
    Matching of contents with one library snapshot.

    Parameters
    ----------
    library : Library
        Library snapshot.
    sources : Sequence[CandidateSource]
        Routes, in the order tried.
    confirmer : TitleConfirmer
        Confirmation by title.
    titles : TitleIndex
        Index of the reverse search.
    resolutions : Resolutions
        Manual resolutions.
    opening_words : int
        Window of the reverse search, in words.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        library: Library,
        sources: Sequence[CandidateSource],
        confirmer: TitleConfirmer,
        titles: TitleIndex,
        resolutions: Resolutions,
        *,
        opening_words: int,
    ) -> None:
        self._library = library
        self._sources = sources
        self._confirmer = confirmer
        self._titles = titles
        self._resolutions = resolutions
        self._opening_words = opening_words

    @classmethod
    def build(
        cls,
        library: Library,
        stored: Mapping[str, str],
        config: MatchingConfig,
        resolutions: Resolutions,
    ) -> "Matcher":
        """
        Assemble a matcher with the default routes.

        Parameters
        ----------
        library : Library
            Library snapshot.
        stored : Mapping[str, str]
            Attachment key by SHA-256 of its stored file.
        config : MatchingConfig
            Thresholds.
        resolutions : Resolutions
            Manual resolutions.

        Returns
        -------
        Matcher
            Matcher trying same file, DOI and name, in that order.
        """
        sources: list[CandidateSource] = [
            SameFileSource(library, stored),
            DoiSource(library),
            NameSource(library, config.name_threshold, config.year_tolerance),
        ]
        return cls(
            library,
            sources,
            TitleConfirmer(config.title_words, config.reject_below),
            TitleIndex(library.regular(), config.title_words, config.reverse_min_words),
            resolutions,
            opening_words=config.opening_words,
        )

    def match_all(self, inventory: Inventory) -> list[Match]:
        """Match every content of an inventory, in inventory order."""
        return [self.match(content) for content in inventory]

    def _require(self, key: str) -> Item:
        """Live item of a key, following merges; a missing item is a configuration error."""
        item = self._library.survivor(key)
        if item is None:
            raise ConfigError(f"item {key} is not in the library snapshot")
        return item

    def _title(self, key: str) -> str:
        """Title of the live item of a key, following merges."""
        return self._require(key).title

    def _assigned(self, content: Content, resolution: Resolution) -> Match:
        """Match decided by an `assign` or `preprint-of` resolution, with its verdict."""
        verdict, share = self._confirmer.verdict(self._title(resolution.item), content.pages)
        status = Status.PREPRINT_OF if resolution.action is Action.PREPRINT_OF else Status.MATCHED
        return Match(
            content.sha256,
            status,
            resolution.item,
            Method.RESOLUTION,
            verdict,
            share,
            resolution.note,
        )

    def _routes(self, content: Content, rejected: set[str], notes: list[str]) -> Match | None:
        """First candidate of the routes that the title does not reject."""
        for source in self._sources:
            candidate = source.propose(content)
            if candidate is None or candidate.item in rejected:
                continue
            if candidate.method is Method.SAME_FILE:
                return Match(
                    content.sha256,
                    Status.MATCHED,
                    candidate.item,
                    candidate.method,
                    Verdict.IDENTICAL,
                )
            verdict, share = self._confirmer.verdict(self._title(candidate.item), content.pages)
            if verdict is Verdict.REJECTED:
                notes.append(
                    f"{candidate.method.value} proposed {candidate.item}, rejected by title"
                )
                continue
            return self._from_candidate(content, candidate, verdict, share)
        return None

    def _reverse(self, content: Content, rejected: set[str], notes: list[str]) -> Match | None:
        """Item whose title opens the first page; several such items leave the match to check."""
        if not content.pages:
            return None
        opening, cited = self._titles.search(content.pages[0], self._opening_words)
        opening = [key for key in opening if key not in rejected]
        if cited:
            notes.append(f"cites {", ".join(cited[:MAX_CITED_NOTED])}")
        if not opening:
            return None
        verdict = Verdict.CONFIRMED if len(opening) == 1 else Verdict.CHECK
        if len(opening) > 1:
            notes.append(f"several titles open the file: {", ".join(opening)}")
        return self._from_candidate(content, Candidate(opening[0], Method.REVERSE), verdict, None)

    @staticmethod
    def _from_candidate(
        content: Content, candidate: Candidate, verdict: Verdict, share: float | None
    ) -> Match:
        """Match of a candidate: matched when confirmed, otherwise left to check."""
        status = Status.MATCHED if verdict is Verdict.CONFIRMED else Status.CHECK
        return Match(content.sha256, status, candidate.item, candidate.method, verdict, share)

    def match(self, content: Content) -> Match:
        """
        Match one content.

        Parameters
        ----------
        content : Content
            Content to match.

        Returns
        -------
        Match
            Outcome; a candidate that is neither identical nor confirmed has status `CHECK` until a
            resolution accepts it.

        Raises
        ------
        ConfigError
            If a resolution names an item absent from the library, including the item of a
            rejection, or accepts a content that no route matches.
        """
        resolution = self._resolutions.get(content.sha256)
        if resolution and resolution.action in (Action.ASSIGN, Action.PREPRINT_OF):
            return self._assigned(content, resolution)
        notes: list[str] = []
        rejected: set[str] = set()
        if resolution and resolution.action is Action.REJECT:
            if not resolution.item:
                note = "; ".join(filter(None, ["rejected by resolution", resolution.note]))
                return Match(content.sha256, Status.ABSENT, note=note)
            self._require(resolution.item)
            rejected.add(resolution.item)
            notes.append(f"{resolution.item} rejected by resolution")
        found = self._routes(content, rejected, notes) or self._reverse(content, rejected, notes)
        if resolution and resolution.action is Action.ACCEPT:
            if found is None:
                raise ConfigError(
                    f"resolution accepts {content.first.relative}, which no route matches"
                )
            notes.append("accepted by resolution")
            found = Match(
                found.sha256, Status.MATCHED, found.item, found.method, found.verdict, found.share
            )
        if resolution and resolution.note:
            notes.append(resolution.note)
        if found is None:
            return Match(content.sha256, Status.ABSENT, note="; ".join(notes))
        return Match(
            found.sha256,
            found.status,
            found.item,
            found.method,
            found.verdict,
            found.share,
            "; ".join(notes),
        )
