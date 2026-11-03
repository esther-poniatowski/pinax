"""
Grouping of the contents that no item holds into works to import.

Several files can hold one work, such as a scan and a digital copy that share a DOI. Contents are
grouped by DOI first; a content without a DOI forms its own work. Each work is imported once, from
its largest PDF.

Classes
-------
Work
    Contents holding one work, and the content to import.

Functions
---------
group_works(contents) -> list[Work]
    Group contents into works.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from pinax.sources.inventory import Content


@dataclass(frozen=True)
class Work:
    """
    Contents holding one work, and the content to import.

    Attributes
    ----------
    work_id : str
        `doi:<doi>` for a group by DOI, `sha256:<sha>` for a content alone.
    doi : str
        Shared DOI, empty for a content alone.
    members : tuple[Content, ...]
        Contents of the work, in inventory order.
    """

    work_id: str
    doi: str
    members: tuple[Content, ...]

    @property
    def representative(self) -> Content | None:
        """Largest content held by a PDF file, or None when no member is a PDF."""
        pdfs = [content for content in self.members if any(f.is_pdf for f in content.files)]
        return max(pdfs, key=lambda content: content.size) if pdfs else None


def group_works(contents: Iterable[Content]) -> list[Work]:
    """
    Group contents into works.

    Parameters
    ----------
    contents : Iterable[Content]
        Contents that no item holds.

    Returns
    -------
    list[Work]
        Works in the order of their first member.
    """
    groups: dict[str, list[Content]] = {}
    for content in contents:
        key = f"doi:{content.doi}" if content.doi else f"sha256:{content.sha256}"
        groups.setdefault(key, []).append(content)
    return [
        Work(key, key.removeprefix("doi:") if key.startswith("doi:") else "", tuple(members))
        for key, members in groups.items()
    ]
