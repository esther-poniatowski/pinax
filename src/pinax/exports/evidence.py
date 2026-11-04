"""
Evidence file: each source file, by SHA-256, and each record, by its export and its position,
mapped to the item that holds it and its citation key.

The route of a source states how its item was reached:

- `imported`: the file belongs to a work imported by one of the given plans;
- `created`: the record belongs to a work created by one of the given plans;
- `matched`: the item existed and the matching found it;
- `preprint-of`: the item holds another version of the work, by manual resolution;
- `unresolved`: no live item with a citation key holds the source.

Classes
-------
Route
    How the item of a file was reached.
EvidenceRow
    One file and its item.
RecordRow
    One record and its item.
EvidenceBuilder
    Builds the evidence rows of an inventory.

Functions
---------
render_evidence(rows, records, header) -> str
    Render the rows as a YAML document, one flow mapping per file and per record.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import yaml

from pinax.checks.locate import ImportLocator
from pinax.library.model import Item, Library
from pinax.library.storage import StorageIndex
from pinax.matching.model import Match, RecordMatch, Status
from pinax.plans.model import ChangePlan, CreateOp, ImportOp
from pinax.records.works import group_records
from pinax.sources.inventory import Inventory

DEFAULT_HEADER = (
    "# Item holding each source file and each record, written by pinax.\n"
    "# Fields of each entry under `files`:\n"
    "#   sha256        content of the file\n"
    "#   folder, file  location of the file, relative to the root of the sources\n"
    "# Fields of each entry under `records`:\n"
    "#   source        export file, relative to the root of the sources\n"
    "#   position      position of the record in its export, from 1\n"
    "#   key, doi      key and DOI of the record, null when the record has none\n"
    "# Fields of every entry:\n"
    "#   route         imported, created, matched, preprint-of or unresolved\n"
    "#   zotero_item   key of the live item holding the source, null when unresolved\n"
    "#   citation_key  citation key of that item, null when unresolved\n"
)
_WIDTH = 1 << 16
"""Line width of the YAML dump, wide enough to keep each entry on one line."""


class Route(StrEnum):
    """How the item of a file was reached."""

    IMPORTED = "imported"
    CREATED = "created"
    MATCHED = "matched"
    PREPRINT_OF = "preprint-of"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class EvidenceRow:
    """
    One file and its item.

    Attributes
    ----------
    sha256 : str
        Content of the file.
    folder : str
        Folder of the file, relative to the sources.
    name : str
        File name.
    route : Route
        How the item was reached.
    item : str
        Key of the live item, empty when unresolved.
    citation_key : str
        Citation key of the item, empty when unresolved.
    """

    sha256: str
    folder: str
    name: str
    route: Route
    item: str = ""
    citation_key: str = ""

    @property
    def label(self) -> str:
        """Path of the file, relative to the root of the sources."""
        return f"{self.folder}/{self.name}"


@dataclass(frozen=True)
class RecordRow:  # pylint: disable=too-many-instance-attributes
    """
    One record and its item.

    Attributes
    ----------
    source : str
        Export file, relative to the root of the sources.
    folder : str
        Folder of the export file.
    position : int
        Position of the record in its export, from 1.
    key : str
        Key of the record, empty when the export gives none.
    doi : str
        DOI of the record, empty when the record has none.
    route : Route
        How the item was reached.
    item : str
        Key of the live item, empty when unresolved.
    citation_key : str
        Citation key of the item, empty when unresolved.
    """

    source: str
    folder: str
    position: int
    key: str
    doi: str
    route: Route
    item: str = ""
    citation_key: str = ""

    @property
    def label(self) -> str:
        """Reference of the record, as `refs.bib#3`."""
        return f"{self.source}#{self.position}"


class EvidenceBuilder:
    """
    Builds the evidence rows of an inventory.

    Parameters
    ----------
    library : Library
        Current library snapshot.
    storage : StorageIndex
        Index of the stored files.
    plans : Sequence[ChangePlan]
        Plans applied to the library, whose imports define the `imported` route.
    """

    def __init__(
        self, library: Library, storage: StorageIndex, plans: Sequence[ChangePlan] = ()
    ) -> None:
        self._library = library
        self._creations: dict[str, CreateOp] = {
            op.identity: op for plan in plans for op in plan.creations
        }
        self._imports: dict[str, ImportOp] = {}
        for plan in plans:
            for op in plan.imports:
                for member in op.members:
                    self._imports.setdefault(member, op)
        located = ImportLocator(library, storage).locate(
            list({op.work_id: op for op in self._imports.values()}.values())
        )
        self._imported: dict[str, Item] = {}
        for work_id, attachment in located.items():
            parent = library.survivor(attachment.parent) if attachment.parent else None
            if parent is not None:
                self._imported[work_id] = parent

    def _item(self, sha256: str, match: Match | None) -> tuple[Route, Item | None]:
        """Route and live item of a content: an import first, then the match."""
        matched = self._library.survivor(match.item) if match and match.item else None
        if match and match.status is Status.CHECK:
            matched = None
        op = self._imports.get(sha256)
        if op is not None:
            return Route.IMPORTED, self._imported.get(op.work_id) or matched
        if match is not None and match.status is Status.PREPRINT_OF:
            return Route.PREPRINT_OF, matched
        if match is not None and match.status is Status.MATCHED:
            return Route.MATCHED, matched
        return Route.UNRESOLVED, None

    def build(self, inventory: Inventory, matches: Sequence[Match]) -> list[EvidenceRow]:
        """
        Build one row per file of the inventory.

        Parameters
        ----------
        inventory : Inventory
            Inventory of the sources.
        matches : Sequence[Match]
            Matches of the contents with the current library.

        Returns
        -------
        list[EvidenceRow]
            Rows in inventory order. A file of an imported work whose import cannot be located
            takes the item of its current match; a file whose item lacks a citation key is
            unresolved.
        """
        by_sha = {match.sha256: match for match in matches}
        rows = []
        for file in inventory.files:
            route, item = self._item(file.sha256, by_sha.get(file.sha256))
            if item is None or not item.citation_key:
                rows.append(EvidenceRow(file.sha256, file.folder, file.name, Route.UNRESOLVED))
                continue
            rows.append(
                EvidenceRow(file.sha256, file.folder, file.name, route, item.key, item.citation_key)
            )
        return rows

    def build_records(
        self, inventory: Inventory, matches: Sequence[RecordMatch]
    ) -> list[RecordRow]:
        """
        Build one row per record of the inventory.

        Parameters
        ----------
        inventory : Inventory
            Inventory of the sources.
        matches : Sequence[RecordMatch]
            Matches of the record works with the current library.

        Returns
        -------
        list[RecordRow]
            Rows in inventory order. A record of a work created by one of the plans takes the item
            that holds the work, when exactly one live item does; a record whose item lacks a
            citation key is unresolved.
        """
        by_identity = {match.identity: match for match in matches}
        rows = []
        for work in group_records(inventory.records):
            route, item = self._record_item(work.identity, by_identity.get(work.identity))
            for record in work.records:
                row = RecordRow(
                    record.source,
                    record.folder,
                    record.position,
                    record.key,
                    record.doi,
                    Route.UNRESOLVED,
                )
                if item is not None and item.citation_key:
                    row = RecordRow(
                        record.source,
                        record.folder,
                        record.position,
                        record.key,
                        record.doi,
                        route,
                        item.key,
                        item.citation_key,
                    )
                rows.append(row)
        order = {record.ref: index for index, record in enumerate(inventory.records)}
        return sorted(rows, key=lambda row: order[row.label])

    def _record_item(self, identity: str, match: RecordMatch | None) -> tuple[Route, Item | None]:
        """Route and live item of a record work: a creation first, then the match."""
        creation = self._creations.get(identity)
        if creation is not None:
            held = [
                item
                for item in self._library.regular()
                if item.holds_work(creation.doi, creation.title)
            ]
            if len(held) == 1:
                return Route.CREATED, held[0]
        if match is None or match.status not in (Status.MATCHED, Status.PREPRINT_OF):
            return Route.UNRESOLVED, None
        route = Route.PREPRINT_OF if match.status is Status.PREPRINT_OF else Route.MATCHED
        return route, self._library.survivor(match.item)


def render_evidence(
    rows: Sequence[EvidenceRow],
    records: Sequence[RecordRow] = (),
    header: str = DEFAULT_HEADER,
) -> str:
    """
    Render the rows as a YAML document, one flow mapping per file and per record.

    Parameters
    ----------
    rows : Sequence[EvidenceRow]
        Evidence rows of the files.
    records : Sequence[RecordRow]
        Evidence rows of the records.
    header : str
        Comment block written before the data.

    Returns
    -------
    str
        YAML document with the lists `files` and `records`, in the order of the rows. Each entry
        stays on one line, so that a change of one source changes one line.
    """
    entries = [
        {
            "sha256": row.sha256,
            "folder": row.folder,
            "file": row.name,
            "route": row.route.value,
            "zotero_item": row.item or None,
            "citation_key": row.citation_key or None,
        }
        for row in rows
    ]
    record_entries = [
        {
            "source": row.source,
            "position": row.position,
            "key": row.key or None,
            "doi": row.doi or None,
            "route": row.route.value,
            "zotero_item": row.item or None,
            "citation_key": row.citation_key or None,
        }
        for row in records
    ]
    body = yaml.safe_dump(
        {"files": entries, "records": record_entries},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=None,
        width=_WIDTH,
    )
    return (header.rstrip("\n") + "\n" if header else "") + body
