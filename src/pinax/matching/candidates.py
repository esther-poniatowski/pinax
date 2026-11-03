"""
Routes that propose an item for a content, tried in order by the matcher.

Classes
-------
CandidateSource
    Protocol of one route.
SameFileSource
    Item whose stored attachment has the same bytes as the content.
DoiSource
    Only item recording the DOI found on the first pages.
NameSource
    Item whose first author, year and title words agree with the file name.
"""

from collections.abc import Mapping
import re
from typing import Protocol

from pinax.library.model import Item, Library
from pinax.matching.model import Candidate, Method
from pinax.sources.inventory import Content
from pinax.text import content_words

_YEAR_PREFIX = re.compile(r"^\d{4}[a-z]?_")
MIN_PREFIX = 4
"""Shortest surname or token compared by prefix: a garbled surname such as `Daggettn` still
matches `daggett`, while shorter prefixes would match unrelated names."""
UNDATED_PENALTY = 0.1
"""Score removed when the year cannot be compared, so that a dated match wins a tie."""


class CandidateSource(Protocol):
    """Protocol of one route."""

    method: Method

    def propose(self, content: Content) -> Candidate | None:
        """
        Item proposed for a content, if any.

        Parameters
        ----------
        content : Content
            Content to match.

        Returns
        -------
        Candidate | None
            Proposed item, or None when the route has no unambiguous answer.
        """


class SameFileSource:
    """
    Item whose stored attachment has the same bytes as the content.

    Parameters
    ----------
    library : Library
        Library snapshot.
    stored : Mapping[str, str]
        Attachment key by SHA-256 of its stored file.
    """

    method = Method.SAME_FILE

    def __init__(self, library: Library, stored: Mapping[str, str]) -> None:
        self._library = library
        self._stored = stored

    def propose(self, content: Content) -> Candidate | None:
        """Parent item of the attachment storing the content, when it is a live regular item."""
        attachment = self._library.get_live(self._stored.get(content.sha256, ""))
        if attachment is None or attachment.parent is None:
            return None
        parent = self._library.survivor(attachment.parent)
        if parent is None or not parent.is_regular:
            return None
        return Candidate(parent.key, self.method)


class DoiSource:
    """
    Only item recording the DOI found on the first pages.

    The DOI on a page can belong to a cited work, so the matcher confirms the candidate by its
    title.

    Parameters
    ----------
    library : Library
        Library snapshot.
    """

    method = Method.DOI

    def __init__(self, library: Library) -> None:
        self._library = library

    def propose(self, content: Content) -> Candidate | None:
        """Item recording the DOI, when exactly one live item does."""
        if not content.doi:
            return None
        keys = self._library.by_doi(content.doi)
        return Candidate(keys[0], self.method) if len(keys) == 1 else None


def _agrees(surname: str, token: str) -> bool:
    """Whether a surname and a file-name token are equal, or one prefixes the other."""
    if surname == token:
        return True
    if min(len(surname), len(token)) < MIN_PREFIX:
        return False
    return surname.startswith(token) or token.startswith(surname)


class NameSource:
    """
    Item whose first author, year and title words agree with the file name.

    A file name such as `2004_Smith_attention_model.pdf` opens on a year, names an author and
    abbreviates the title. Library dates can be empty or wrong, so an item without a plausible
    year is not excluded by the year test, only penalized.

    Parameters
    ----------
    library : Library
        Library snapshot.
    threshold : float
        Lowest overlap score accepted.
    year_tolerance : int
        Largest difference between the year of the name and the year of the item.
    """

    method = Method.NAME

    def __init__(self, library: Library, threshold: float, year_tolerance: int) -> None:
        self._items = list(library.regular())
        self._threshold = threshold
        self._year_tolerance = year_tolerance

    def _score(self, item: Item, year: int | None, tokens: set[str]) -> float | None:
        """Overlap of an item with the name tokens, or None when its year or authors disagree."""
        item_year = item.year
        if year is not None and item_year is not None:
            if abs(item_year - year) > self._year_tolerance:
                return None
        surnames = {word for name in item.surnames for word in content_words(name)}
        if not any(_agrees(surname, token) for surname in surnames for token in tokens):
            return None
        title = content_words(item.title)
        overlap = len(title & tokens) / max(1, min(len(title), len(tokens - surnames)))
        if year is None or item_year is None:
            overlap -= UNDATED_PENALTY
        return overlap

    def propose(self, content: Content) -> Candidate | None:
        """Best-scoring item when its score reaches the threshold; the first item wins a tie."""
        file = content.first
        stem = _YEAR_PREFIX.sub("", file.name.rsplit(".", 1)[0])
        tokens = content_words(stem.replace("_", " "))
        year = int(file.year) if file.year else None
        best: Candidate | None = None
        for item in self._items:
            score = self._score(item, year, tokens)
            if score is not None and (best is None or score > best.score):
                best = Candidate(item.key, self.method, score)
        return best if best is not None and best.score >= self._threshold else None
