"""
Bibliographic records read from exports, and the identity of the work each one describes.

A record is identified by its export file and its position in that file, never by its key: two
records of one export can share a key while describing two works. The identity of a record is its
normalized DOI, or else its normalized title and year, so that records of several exports of the
same works describe one work.

Classes
-------
RecordCreator
    One creator of a record.
Record
    One entry of an export file.
"""

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
import re
from typing import Any

from pinax.text import normalize_doi, words

_YEAR = re.compile(r"\b(1[5-9]|20)\d\d\b")


@dataclass(frozen=True)
class RecordCreator:
    """
    One creator of a record.

    Attributes
    ----------
    last_name : str
        Last name, with its particles, or the full name of an institution.
    first_name : str
        First names, empty for an institution.
    creator_type : str
        Zotero creator type, such as `author` or `editor`.
    """

    last_name: str
    first_name: str = ""
    creator_type: str = "author"


@dataclass(frozen=True)
class Record:  # pylint: disable=too-many-instance-attributes
    """
    One entry of an export file.

    Attributes
    ----------
    source : str
        Export file, relative to the root of the sources.
    position : int
        Position of the entry in its file, from 1.
    key : str
        Key of the entry in the export, empty when the format has none; keys can repeat.
    item_type : str
        Zotero item type, empty for a record that only a DOI describes.
    title : str
        Title, empty for a record that only a DOI describes.
    creators : tuple[RecordCreator, ...]
        Creators in order.
    date : str
        Date as written in the export.
    doi : str
        Normalized DOI, empty when the record has none.
    fields : dict[str, str]
        Other fields, under their Zotero names, such as `publicationTitle` or `pages`.
    """

    source: str
    position: int
    key: str
    item_type: str
    title: str
    creators: tuple[RecordCreator, ...] = ()
    date: str = ""
    doi: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        """Reference of the record: its export file and its position, as `refs.bib#3`."""
        return f"{self.source}#{self.position}"

    @property
    def folder(self) -> str:
        """Folder of the export file, relative to the root, `.` for the root."""
        return str(PurePosixPath(self.source).parent)

    @property
    def year(self) -> int | None:
        """Year of the date, None when the date holds no plausible year."""
        found = _YEAR.search(self.date)
        return int(found.group(0)) if found else None

    @property
    def normalized_title(self) -> str:
        """Title folded in case and accents, as compared with the titles of the library."""
        return " ".join(words(self.title))

    @property
    def has_metadata(self) -> bool:
        """Whether the record describes its work beyond a DOI, as a creation needs."""
        return bool(self.item_type and self.title)

    @property
    def identity(self) -> str:
        """
        Identity of the work: `doi:<doi>`, else `title:<title>|<year>`, else `record:<ref>`.

        Examples
        --------
        >>> Record("a.bib", 1, "k", "book", "The Shape of Signals", date="2001").identity
        'title:the shape signals|2001'
        >>> Record("a.bib", 2, "k", "book", "x", doi="10.5555/X").identity
        'doi:10.5555/x'
        """
        if self.doi:
            return f"doi:{normalize_doi(self.doi)}"
        if self.normalized_title:
            year = self.year
            return f"title:{self.normalized_title}" + (f"|{year}" if year else "")
        return f"record:{self.ref}"

    def to_json(self) -> dict[str, Any]:
        """Serializable form of the record."""
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Record":
        """Rebuild a record from its serialized form."""
        return cls(
            source=data["source"],
            position=int(data["position"]),
            key=data.get("key", ""),
            item_type=data.get("item_type", ""),
            title=data.get("title", ""),
            creators=tuple(RecordCreator(**creator) for creator in data.get("creators", [])),
            date=data.get("date", ""),
            doi=data.get("doi", ""),
            fields=dict(data.get("fields", {})),
        )
