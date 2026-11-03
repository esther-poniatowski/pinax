"""
Evidence table: each source file, by SHA-256, mapped to the item that holds it and its citation key.

The route of a file states how its item was reached:

- `imported`: the file belongs to a work imported by one of the given plans;
- `matched`: the item existed and the matching found it;
- `preprint-of`: the item holds another version of the work, by manual resolution;
- `unresolved`: no live item with a citation key holds the file.

Classes
-------
Route
    How the item of a file was reached.
EvidenceRow
    One file and its item.
EvidenceBuilder
    Builds the evidence rows of an inventory.

Functions
---------
write_evidence(rows) -> str
    Render the rows as a tab-separated table.
"""

from collections.abc import Sequence
import csv
from dataclasses import dataclass
from enum import StrEnum
import io

from pinax.checks.locate import ImportLocator
from pinax.library.model import Item, Library
from pinax.library.storage import StorageIndex
from pinax.matching.model import Match, Status
from pinax.plans.model import ChangePlan, ImportOp
from pinax.sources.inventory import Inventory

COLUMNS = ("sha256", "folder", "file", "route", "zotero_item", "citation_key")


class Route(StrEnum):
    """How the item of a file was reached."""

    IMPORTED = "imported"
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


def write_evidence(rows: Sequence[EvidenceRow]) -> str:
    """
    Render the rows as a tab-separated table.

    Parameters
    ----------
    rows : Sequence[EvidenceRow]
        Evidence rows.

    Returns
    -------
    str
        Table with the header `COLUMNS`, one line per row.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(
            [row.sha256, row.folder, row.name, row.route.value, row.item, row.citation_key]
        )
    return buffer.getvalue()
