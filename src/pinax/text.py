"""
Normalization of titles, names and identifiers, shared by matching, checks and inventory.

Every comparison of a title with the text of a page goes through `words`, so that the inventory,
the matching and the checks fold accents, case and punctuation identically.

Functions
---------
fold(text) -> str
    Strip accents and fold case.
words(text) -> list[str]
    Split a text into the words that titles and pages are compared on.
content_words(text) -> set[str]
    Words of `words` without stop words, for overlap scores.
title_head(title, length) -> str
    Opening words of a title, joined by single spaces.
contains_sequence(haystack, head) -> bool
    Whether a head occurs in a word sequence on word boundaries.
sequence_position(haystack, head) -> int | None
    Word index at which a head first occurs in a word sequence.
joined(haystack) -> str
    Padded text of a word sequence, searched by `position_in_joined`.
position_in_joined(text, head) -> int | None
    Word index at which a head first occurs in a padded text.
normalize_doi(doi) -> str
    Canonical form of a DOI.
find_doi(text) -> str
    First DOI written in a text, normalized.

Examples
--------
>>> words("Memory: and Perception (2nd ed.)")
['memory', 'and', 'perception', '2nd']
>>> title_head("The attentional blink: a review of models", 3)
'the attentional blink'
>>> normalize_doi("https://doi.org/10.1000/ABC.123 ")
'10.1000/abc.123'
"""

import re
import unicodedata

STOP_WORDS = frozenset(
    {"the", "of", "and", "a", "an", "in", "on", "to", "for", "with", "by", "from", "at", "as", "is"}
    | {"its"}
)
"""Words ignored by overlap scores, since they carry no information about a title."""

MIN_WORD_LENGTH = 3
"""Shortest word kept by `words`: shorter tokens are mostly initials, page numbers or articles."""

_SPLIT = re.compile(r"[^a-z0-9]+")
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
_DOI_PREFIX = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:\s*)")
_DOI_TRAILING = ".,;)]"


def fold(text: str) -> str:
    """
    Strip accents and fold case.

    Parameters
    ----------
    text : str
        Any text.

    Returns
    -------
    str
        ASCII text in lower case.
    """
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def words(text: str) -> list[str]:
    """
    Split a text into the words that titles and pages are compared on.

    Parameters
    ----------
    text : str
        Title, file name or page text.

    Returns
    -------
    list[str]
        Folded alphanumeric tokens of at least `MIN_WORD_LENGTH` characters, in order.
    """
    return [word for word in _SPLIT.split(fold(text)) if len(word) >= MIN_WORD_LENGTH]


def content_words(text: str) -> set[str]:
    """
    Words of `words` without stop words, for overlap scores.

    Parameters
    ----------
    text : str
        Title or file name.

    Returns
    -------
    set[str]
        Distinct words that are not stop words.
    """
    return {word for word in words(text) if word not in STOP_WORDS}


def title_head(title: str, length: int) -> str:
    """
    Opening words of a title, joined by single spaces.

    Parameters
    ----------
    title : str
        Title of an item.
    length : int
        Number of words kept.

    Returns
    -------
    str
        The first `length` words of `words(title)`, or an empty string for a title without words.
    """
    return " ".join(words(title)[:length])


def sequence_position(haystack: list[str], head: str) -> int | None:
    """
    Word index at which a head first occurs in a word sequence.

    Parameters
    ----------
    haystack : list[str]
        Words of a page, as returned by `words`.
    head : str
        Words joined by single spaces, as returned by `title_head`.

    Returns
    -------
    int | None
        Index of the first word of the earliest occurrence, or None when the head is empty or
        absent. Occurrences are matched on word boundaries only.

    Examples
    --------
    >>> sequence_position(["a", "start", "attention", "model"], "attention model")
    2
    >>> sequence_position(["restart", "model"], "start model") is None
    True
    """
    return position_in_joined(joined(haystack), head)


def joined(haystack: list[str]) -> str:
    """
    Word sequence joined by single spaces and padded by one space on each side.

    Parameters
    ----------
    haystack : list[str]
        Words, as returned by `words`.

    Returns
    -------
    str
        Text searched by `position_in_joined`; joining once serves many searches in one page.
    """
    return f" {" ".join(haystack)} "


def position_in_joined(text: str, head: str) -> int | None:
    """
    Word index at which a head first occurs in a text returned by `joined`.

    Parameters
    ----------
    text : str
        Padded word sequence.
    head : str
        Words joined by single spaces.

    Returns
    -------
    int | None
        Index of the first word of the earliest occurrence, or None.
    """
    if not head:
        return None
    offset = text.find(f" {head} ")
    if offset < 0:
        return None
    return text.count(" ", 0, offset)


def contains_sequence(haystack: list[str], head: str) -> bool:
    """
    Whether a head occurs in a word sequence on word boundaries.

    Parameters
    ----------
    haystack : list[str]
        Words of a page, as returned by `words`.
    head : str
        Words joined by single spaces.

    Returns
    -------
    bool
        True when `sequence_position` finds the head.
    """
    return sequence_position(haystack, head) is not None


def normalize_doi(doi: str) -> str:
    """
    Canonical form of a DOI: no URL or `doi:` prefix, no surrounding space, lower case.

    Parameters
    ----------
    doi : str
        DOI as written in a record or a page.

    Returns
    -------
    str
        Normalized DOI, or an empty string for an empty input.
    """
    return _DOI_PREFIX.sub("", doi.strip().lower()).rstrip(_DOI_TRAILING)


def find_doi(text: str) -> str:
    """
    First DOI written in a text, normalized.

    Parameters
    ----------
    text : str
        Page text or a field such as `extra`.

    Returns
    -------
    str
        Normalized DOI, or an empty string when the text holds none.

    Examples
    --------
    >>> find_doi("Published as doi:10.1162/jocn.1989.1.3.244.")
    '10.1162/jocn.1989.1.3.244'
    """
    found = _DOI.search(text)
    return normalize_doi(found.group(1)) if found else ""
