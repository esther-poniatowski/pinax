"""
Confirmation of a match by the text of the file.

A share of title words found in the page confirms too easily: a short title of a few common words
passes against many pages. A match is therefore confirmed only when the opening
words of the title appear in sequence. A DOI or a title found on a page can belong to a cited work,
so the reverse search confirms an item only when its title opens the first page.

Classes
-------
TitleConfirmer
    Verdict on a candidate from the text of the first pages.
TitleIndex
    Opening words of every library title, for the reverse search.
"""

from collections.abc import Iterable, Sequence

from pinax.library.model import Item
from pinax.matching.model import Verdict
from pinax.text import joined, position_in_joined, sequence_position, title_head, words


class TitleConfirmer:
    """
    Verdict on a candidate from the text of the first pages.

    Parameters
    ----------
    title_words : int
        Opening title words that must appear in sequence.
    reject_below : float
        Share of title words below which a candidate is rejected.
    """

    def __init__(self, title_words: int, reject_below: float) -> None:
        self.title_words = title_words
        self.reject_below = reject_below

    def verdict(self, title: str, pages: Sequence[str]) -> tuple[Verdict, float | None]:
        """
        Verdict on a title against the text of the first pages.

        Parameters
        ----------
        title : str
            Title of the candidate item.
        pages : Sequence[str]
            Text of the first pages of the file.

        Returns
        -------
        tuple[Verdict, float | None]
            Verdict, and the share of title words found in the pages (None without text).

        Examples
        --------
        >>> confirmer = TitleConfirmer(title_words=8, reject_below=0.5)
        >>> confirmer.verdict("A model of the blink", ["Journal X. A model of the blink. Abstract"])
        (<Verdict.CONFIRMED: 'confirmed'>, 1.0)
        >>> confirmer.verdict("A model of the blink", [])
        (<Verdict.CHECK: 'check'>, None)
        """
        page = words(" ".join(pages))
        title_tokens = words(title)
        if not page or not title_tokens:
            return Verdict.CHECK, None
        present = set(page)
        share = sum(word in present for word in title_tokens) / len(title_tokens)
        if sequence_position(page, title_head(title, self.title_words)) is not None:
            return Verdict.CONFIRMED, share
        if share < self.reject_below:
            return Verdict.REJECTED, share
        return Verdict.CHECK, share


class TitleIndex:
    """
    Opening words of every library title, for the reverse search.

    Parameters
    ----------
    items : Iterable[Item]
        Regular items of the library.
    title_words : int
        Opening title words looked for.
    min_words : int
        Shortest title looked for; shorter titles occur in too many pages.
    """

    def __init__(self, items: Iterable[Item], title_words: int, min_words: int) -> None:
        self._heads: dict[str, list[str]] = {}
        for item in items:
            if len(words(item.title)) >= min_words:
                self._heads.setdefault(title_head(item.title, title_words), []).append(item.key)

    def search(self, first_page: str, opening_words: int) -> tuple[list[str], list[str]]:
        """
        Items whose title occurs in the first page of a file.

        Parameters
        ----------
        first_page : str
            Text of the first page.
        opening_words : int
            Window, in words from the start of the page, in which a title opens the file.

        Returns
        -------
        tuple[list[str], list[str]]
            Keys of the items whose title starts within the window, then keys of the items whose
            title occurs only later, as a citation would.
        """
        page = words(first_page)
        opening: list[str] = []
        cited: list[str] = []
        if not page:
            return opening, cited
        text = joined(page)
        for head, keys in self._heads.items():
            position = position_in_joined(text, head)
            if position is None:
                continue
            (opening if position < opening_words else cited).extend(keys)
        return sorted(set(opening)), sorted(set(cited))
