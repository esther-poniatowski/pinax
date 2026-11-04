"""
Readers of record exports, one per format, mapping each entry to a record under Zotero names.

Every reader fails on an entry that it cannot read, rather than skipping it: an export that loses
an entry silently leaves a work out of the reconciliation without report.

Classes
-------
RecordReader
    Protocol of the reader of one format.
BibtexReader
    BibTeX, through `bibtexparser`.
RisReader
    RIS, a format of tagged lines.
ZoteroCsvReader
    CSV export of Zotero, with its named columns.
DoiListReader
    One DOI per line.

Functions
---------
reader(name) -> RecordReader
    Reader of a format, by its name in the configuration.
"""

from collections.abc import Iterable, Mapping
import csv
import io
from pathlib import Path
import re
from typing import Any, Protocol

from bibtexparser.entrypoint import parse_string
from bibtexparser.middlewares import LatexDecodingMiddleware, SeparateCoAuthors, SplitNameParts
from bibtexparser.model import DuplicateBlockKeyBlock, Entry, ParsingFailedBlock

from pinax.errors import ArtifactError
from pinax.records.model import Record, RecordCreator
from pinax.text import find_doi, normalize_doi

_SPACES = re.compile(r"\s+")
_DASHES = re.compile(r"\s*[‐-―-]+\s*")
_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])  -(?: (.*))?$")


def _clean(value: str) -> str:
    """Value with its runs of white space, line breaks included, reduced to one space."""
    return _SPACES.sub(" ", value).strip()


def _pages(value: str) -> str:
    """Page range with a plain hyphen, as Zotero writes it."""
    return _DASHES.sub("-", _clean(value))


def _people(text: str, creator_type: str) -> list[RecordCreator]:
    """Creators of a `Last, First; Last, First` list; a name without comma is one field."""
    people = []
    for name in (part.strip() for part in text.split(";")):
        if not name:
            continue
        last, _, first = name.partition(",")
        people.append(RecordCreator(_clean(last), _clean(first), creator_type))
    return people


class RecordReader(Protocol):
    """Protocol of the reader of one format."""

    def read(self, path: Path, source: str) -> list[Record]:
        """
        Records of an export file.

        Parameters
        ----------
        path : Path
            Export file.
        source : str
            Path of the file relative to the root of the sources, recorded in each record.

        Returns
        -------
        list[Record]
            Records in file order.

        Raises
        ------
        ArtifactError
            If an entry cannot be read.
        """


BIBTEX_TYPES = {
    "article": "journalArticle",
    "inproceedings": "conferencePaper",
    "conference": "conferencePaper",
    "incollection": "bookSection",
    "inbook": "bookSection",
    "book": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "unpublished": "manuscript",
    "online": "webpage",
    "electronic": "webpage",
    "www": "webpage",
}
"""Zotero type of each BibTeX type; a `misc` entry is a preprint when it names an arXiv identifier,
and a document otherwise."""

BIBTEX_FIELDS = {
    "journal": "publicationTitle",
    "journaltitle": "publicationTitle",
    "volume": "volume",
    "number": "issue",
    "publisher": "publisher",
    "address": "place",
    "location": "place",
    "isbn": "ISBN",
    "issn": "ISSN",
    "url": "url",
    "abstract": "abstractNote",
    "series": "series",
    "edition": "edition",
    "language": "language",
    "note": "extra",
}
"""Zotero name of each BibTeX field that maps one to one."""


class BibtexReader:
    """
    BibTeX, through `bibtexparser`.

    The parser reads nested braces and fields spanning several lines. An entry whose key repeats an
    earlier key is kept as a record of its own, at its position; an entry that does not parse
    stops the reading.
    """

    _MIDDLEWARES = (LatexDecodingMiddleware, SeparateCoAuthors, SplitNameParts)

    def _parse(self, text: str) -> Any:
        """Library parsed with LaTeX decoding and split names."""
        return parse_string(
            text, append_middleware=[middleware() for middleware in self._MIDDLEWARES]
        )

    def read(self, path: Path, source: str) -> list[Record]:
        """Records of a BibTeX file, one per entry, repeated keys included."""
        library = self._parse(path.read_text(encoding="utf-8"))
        entries: list[Entry] = []
        for block in library.blocks:
            if isinstance(block, ParsingFailedBlock) and not isinstance(
                block, DuplicateBlockKeyBlock
            ):
                raise ArtifactError(
                    f"{source}: the entry at line {block.start_line} does not parse"
                )
            if isinstance(block, DuplicateBlockKeyBlock):
                # The middlewares skip a block flagged as a duplicate: parse it again alone.
                entries.extend(self._parse(block.raw or "").entries)
            elif isinstance(block, Entry):
                entries.append(block)
        return [self._record(entry, source, index) for index, entry in enumerate(entries, 1)]

    @staticmethod
    def _creators(entry: Entry, name: str, creator_type: str) -> list[RecordCreator]:
        """Creators of a name field split into parts by the middlewares."""
        field = entry.fields_dict.get(name)
        if field is None:
            return []
        people = []
        for person in field.value:
            last = " ".join([*person.von, *person.last, *person.jr])
            people.append(RecordCreator(_clean(last), _clean(" ".join(person.first)), creator_type))
        return people

    def _record(self, entry: Entry, source: str, position: int) -> Record:
        """Record of one entry."""
        values = {
            name.lower(): _clean(str(field.value))
            for name, field in entry.fields_dict.items()
            if name.lower() not in ("author", "editor")
        }
        kind = entry.entry_type.lower()
        eprint = values.get("eprint", "")
        arxiv = (
            "arxiv" in (values.get("archiveprefix", "") + values.get("howpublished", "")).lower()
        )
        item_type = BIBTEX_TYPES.get(kind, "preprint" if kind == "misc" and arxiv else "document")
        fields = {
            BIBTEX_FIELDS[name]: value for name, value in values.items() if name in BIBTEX_FIELDS
        }
        if "pages" in values:
            fields["pages"] = _pages(values["pages"])
        if "booktitle" in values:
            fields["proceedingsTitle" if item_type == "conferencePaper" else "bookTitle"] = values[
                "booktitle"
            ]
        for name in ("school", "institution"):
            if name in values:
                fields["university" if item_type == "thesis" else "institution"] = values[name]
        if item_type == "thesis":
            fields["thesisType"] = "PhD thesis" if kind == "phdthesis" else "Master's thesis"
        if item_type == "report" and "issue" in fields:
            fields["reportNumber"] = fields.pop("issue")
        if item_type == "preprint" and eprint:
            fields["archiveID"] = f"arXiv:{eprint}"
        date = values.get("date") or " ".join(
            filter(None, [values.get("year"), values.get("month")])
        )
        return Record(
            source=source,
            position=position,
            key=entry.key,
            item_type=item_type,
            title=values.get("title", ""),
            creators=tuple(
                self._creators(entry, "author", "author")
                + self._creators(entry, "editor", "editor")
            ),
            date=date,
            doi=normalize_doi(values.get("doi", "")),
            fields=fields,
        )


RIS_TYPES = {
    "JOUR": "journalArticle",
    "JFULL": "journalArticle",
    "MGZN": "magazineArticle",
    "NEWS": "newspaperArticle",
    "CONF": "conferencePaper",
    "CPAPER": "conferencePaper",
    "CHAP": "bookSection",
    "BOOK": "book",
    "EBOOK": "book",
    "THES": "thesis",
    "RPRT": "report",
    "ELEC": "webpage",
    "WEB": "webpage",
    "UNPB": "manuscript",
    "MANSCPT": "manuscript",
}
"""Zotero type of each RIS type; any other type is a document."""

RIS_FIELDS = {
    "VL": "volume",
    "IS": "issue",
    "PB": "publisher",
    "CY": "place",
    "UR": "url",
    "AB": "abstractNote",
    "N2": "abstractNote",
    "LA": "language",
    "N1": "extra",
}
"""Zotero name of each RIS tag that maps one to one."""


class RisReader:
    """
    RIS, a format of tagged lines.

    Each line holds a tag of two characters, two spaces, a hyphen and the value; a line without a
    tag continues the value of the previous line. The tag `ER` closes a record, and a record left
    open at the end of the file stops the reading.
    """

    def read(self, path: Path, source: str) -> list[Record]:
        """Records of a RIS file, one per `TY` ... `ER` block."""
        records: list[Record] = []
        current: list[tuple[str, str]] | None = None
        for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw.rstrip()
            found = _RIS_LINE.match(line)
            if found is None:
                if not line.strip():
                    continue
                if current is None:
                    raise ArtifactError(f"{source}: line {number} lies outside a record")
                # A line without a tag continues the value of the previous tag.
                tag, value = current.pop()
                current.append((tag, f"{value} {line.strip()}"))
                continue
            tag, value = found.group(1), (found.group(2) or "").strip()
            if tag == "TY":
                if current is not None:
                    raise ArtifactError(f"{source}: a record opens at line {number} before `ER`")
                current = [(tag, value)]
            elif current is None:
                raise ArtifactError(f"{source}: tag {tag} at line {number} lies outside a record")
            elif tag == "ER":
                records.append(self._record(current, source, len(records) + 1))
                current = None
            else:
                current.append((tag, value))
        if current is not None:
            raise ArtifactError(f"{source}: the last record is not closed by `ER`")
        return records

    @staticmethod
    def _record(tags: list[tuple[str, str]], source: str, position: int) -> Record:
        """Record of the tags of one block."""
        values: dict[str, list[str]] = {}
        for tag, value in tags:
            values.setdefault(tag, []).append(_clean(value))

        def first(*names: str) -> str:
            return next((values[name][0] for name in names if values.get(name)), "")

        item_type = RIS_TYPES.get(first("TY"), "document")
        fields = {name: first(tag) for tag, name in RIS_FIELDS.items() if first(tag)}
        container = first("JO", "JF", "T2", "BT", "JA")
        if container:
            name = {"conferencePaper": "proceedingsTitle", "bookSection": "bookTitle"}
            fields[name.get(item_type, "publicationTitle")] = container
        pages = "-".join(filter(None, [first("SP"), first("EP")]))
        if pages:
            fields["pages"] = _pages(pages)
        number = first("SN")
        if number:
            fields["ISBN" if item_type in ("book", "bookSection") else "ISSN"] = number
        creators = [
            RecordCreator(_clean(last), _clean(given), creator_type)
            for tags_of, creator_type in ((("AU", "A1"), "author"), (("ED", "A2"), "editor"))
            for tag in tags_of
            for last, _, given in (name.partition(",") for name in values.get(tag, []))
        ]
        date = first("DA", "PY", "Y1").strip("/ ")
        return Record(
            source=source,
            position=position,
            key=first("ID"),
            item_type=item_type,
            title=first("TI", "T1"),
            creators=tuple(creators),
            date=_clean(date),
            doi=normalize_doi(first("DO")),
            fields=fields,
        )


CSV_FIELDS = {
    "Url": "url",
    "Abstract Note": "abstractNote",
    "Pages": "pages",
    "Issue": "issue",
    "Volume": "volume",
    "Publisher": "publisher",
    "Place": "place",
    "Language": "language",
    "ISBN": "ISBN",
    "ISSN": "ISSN",
    "Series": "series",
    "Extra": "extra",
}
"""Zotero name of each column of the CSV export that maps one to one."""

_CSV_REQUIRED = ("Item Type", "Title")


class ZoteroCsvReader:
    """
    CSV export of Zotero, with its named columns.

    The `csv` module reads quoted values spanning several lines. The columns `Item Type` and
    `Title` are required, so that another CSV file is refused rather than misread.
    """

    def read(self, path: Path, source: str) -> list[Record]:
        """Records of a CSV export, one per row."""
        rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"), newline=""))
        missing = [name for name in _CSV_REQUIRED if name not in (rows.fieldnames or [])]
        if missing:
            raise ArtifactError(f"{source}: not a CSV export of Zotero, no column {missing[0]}")
        return [self._record(row, source, index) for index, row in enumerate(rows, 1)]

    @staticmethod
    def _record(row: Mapping[str, str | None], source: str, position: int) -> Record:
        """Record of one row."""

        def value(name: str) -> str:
            return _clean(row.get(name) or "")

        item_type = value("Item Type")
        fields = {name: value(column) for column, name in CSV_FIELDS.items() if value(column)}
        if "pages" in fields:
            fields["pages"] = _pages(fields["pages"])
        container = value("Publication Title")
        if container:
            name = {"conferencePaper": "proceedingsTitle", "bookSection": "bookTitle"}
            fields[name.get(item_type, "publicationTitle")] = container
        creators = _people(value("Author"), "author") + _people(value("Editor"), "editor")
        return Record(
            source=source,
            position=position,
            key=value("Key"),
            item_type=item_type,
            title=value("Title"),
            creators=tuple(creators),
            date=value("Date") or value("Publication Year"),
            doi=normalize_doi(value("DOI")),
            fields=fields,
        )


class DoiListReader:
    """
    One DOI per line; a blank line or a line opening with `#` is skipped.

    A line without a DOI stops the reading, since it may hold a reference that would be lost.
    """

    def read(self, path: Path, source: str) -> list[Record]:
        """Records holding only a DOI, one per line."""
        records: list[Record] = []
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            doi = find_doi(text)
            if not doi:
                raise ArtifactError(f"{source}: line {number} holds no DOI")
            records.append(Record(source, len(records) + 1, "", "", "", doi=doi))
        return records


READERS: dict[str, RecordReader] = {
    "bibtex": BibtexReader(),
    "ris": RisReader(),
    "zotero-csv": ZoteroCsvReader(),
    "doi-list": DoiListReader(),
}
"""Reader of each format, by its name in the configuration."""


def reader(name: str) -> RecordReader:
    """
    Reader of a format, by its name in the configuration.

    Raises
    ------
    ArtifactError
        If no reader has the name.
    """
    if name not in READERS:
        raise ArtifactError(f"no reader of format {name}; known: {", ".join(READERS)}")
    return READERS[name]


def formats() -> Iterable[str]:
    """Names of the formats that a configuration may declare."""
    return READERS.keys()
