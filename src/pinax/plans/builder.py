"""
Construction of a change plan from the matches.

Classes
-------
PlanBuilder
    Builds the plan of one reconciliation from an inventory, its matches and the library.
"""

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from pinax.errors import PlanError
from pinax.library.model import Item, Library
from pinax.matching.model import Match, Status
from pinax.matching.works import Work, group_works
from pinax.plans.model import (
    AttachOp,
    ChangePlan,
    CorrectOp,
    Destination,
    FileOp,
    FileRef,
    ImportOp,
    SkippedWork,
)
from pinax.sources.inventory import Content, Inventory


def _unique_name(name: str, taken: set[str]) -> str:
    """Name unique within a folder, ignoring case, by a numeric suffix; records it as taken."""
    candidate, path, counter = name, PurePosixPath(name), 2
    while candidate.lower() in taken:
        candidate = f"{path.stem}_{counter}{path.suffix}"
        counter += 1
    taken.add(candidate.lower())
    return candidate


class PlanBuilder:
    """
    Builds the plan of one reconciliation from an inventory, its matches and the library.

    Parameters
    ----------
    library : Library
        Library snapshot taken before the change.
    inventory : Inventory
        Inventory of the sources.
    destination : str
        Key of the collection receiving filed and imported items.
    scope : str
        Key of the collection whose sub-tree counts as filed.

    Raises
    ------
    PlanError
        If the destination or the scope is not a collection of the library. A missing collection is
        created by the researcher in Zotero; the plan never creates one.
    """

    def __init__(
        self, library: Library, inventory: Inventory, destination: str, scope: str
    ) -> None:
        for key in (destination, scope):
            if key not in library.collections:
                raise PlanError(
                    f"collection {key} is not in the library; create it in Zotero first"
                )
        self._library = library
        self._inventory = inventory
        self._destination = Destination(
            key=destination,
            name=library.collections[destination].name,
            path=library.collection_path(destination),
        )
        self._scope = scope

    def _file_ref(self, content: Content) -> FileRef:
        """Reference to the first PDF file of a content."""
        file = next((f for f in content.files if f.is_pdf), content.first)
        return FileRef(
            path=str(self._inventory.path(file)),
            sha256=content.sha256,
            md5=file.md5,
            size=file.size,
        )

    def _item(self, key: str) -> Item:
        """Live item holding a matched key, following merges."""
        item = self._library.survivor(key)
        if item is None:
            raise PlanError(f"matched item {key} is not in the library snapshot")
        return item

    def _attachments(self, matches: Sequence[Match]) -> list[AttachOp]:
        """Largest matched PDF for each matched item without a PDF."""
        by_item: dict[str, list[Content]] = {}
        for match in matches:
            if match.status is Status.MATCHED:
                key = self._item(match.item).key
                by_item.setdefault(key, []).append(self._inventory.contents[match.sha256])
        ops = []
        for key, contents in by_item.items():
            pdfs = [c for c in contents if any(f.is_pdf for f in c.files)]
            if self._library.pdfs(key) or not pdfs:
                continue
            item = self._library.items[key]
            largest = max(pdfs, key=lambda content: content.size)
            ops.append(AttachOp(key, item.citation_key, item.title, self._file_ref(largest)))
        return ops

    def _filings(self, matches: Sequence[Match]) -> list[FileOp]:
        """Matched and preprint items outside the scope."""
        keys = [
            self._item(match.item).key
            for match in matches
            if match.status in (Status.MATCHED, Status.PREPRINT_OF)
        ]
        ops = []
        for key in dict.fromkeys(keys):
            item = self._library.items[key]
            if self._library.in_subtree(item, self._scope):
                continue
            current = tuple(self._library.collection_path(c) for c in item.collections)
            ops.append(FileOp(key, item.citation_key, item.title, current))
        return ops

    def _imports(self, works: Iterable[Work]) -> tuple[list[ImportOp], list[SkippedWork]]:
        """One import per work with a PDF; the other works are skipped."""
        imports: list[ImportOp] = []
        skipped: list[SkippedWork] = []
        taken: set[str] = set()
        for work in works:
            files = tuple(str(f.relative) for c in work.members for f in c.files)
            representative = work.representative
            if representative is None:
                skipped.append(SkippedWork(work.work_id, "no PDF file holds the work", files))
                continue
            name = next(f.name for f in representative.files if f.is_pdf)
            imports.append(
                ImportOp(
                    work_id=work.work_id,
                    doi=work.doi,
                    file=self._file_ref(representative),
                    staged_name=_unique_name(name, taken),
                    members=tuple(c.sha256 for c in work.members),
                )
            )
        return imports, skipped

    def _corrections(self, corrections: Sequence[CorrectOp]) -> list[CorrectOp]:
        """Corrections, after checking that each item is live."""
        missing = [op.item for op in corrections if self._library.get_live(op.item) is None]
        if missing:
            raise PlanError(f"corrected items not in the library: {", ".join(missing)}")
        return list(corrections)

    def build(self, matches: Sequence[Match], corrections: Sequence[CorrectOp] = ()) -> ChangePlan:
        """
        Build the plan.

        Parameters
        ----------
        matches : Sequence[Match]
            Matches of every content of the inventory.
        corrections : Sequence[CorrectOp]
            Corrections of item records.

        Returns
        -------
        ChangePlan
            Imports of the absent works, attachments to matched items without a PDF, filings of
            matched items outside the scope, and the corrections. A preprint never becomes the PDF
            of the published item, so preprint matches only lead to filings.

        Raises
        ------
        PlanError
            If a match still awaits a check, or a corrected or matched item is missing.
        """
        pending = [
            str(self._inventory.contents[m.sha256].first.relative)
            for m in matches
            if m.status is Status.CHECK
        ]
        if pending:
            raise PlanError(
                "matches await a check; resolve them before planning:\n  " + "\n  ".join(pending)
            )
        absent = [self._inventory.contents[m.sha256] for m in matches if m.status is Status.ABSENT]
        imports, skipped = self._imports(group_works(absent))
        return ChangePlan(
            destination=self._destination,
            scope=self._scope,
            imports=tuple(imports),
            attachments=tuple(self._attachments(matches)),
            filings=tuple(self._filings(matches)),
            corrections=tuple(self._corrections(corrections)),
            skipped=tuple(skipped),
        )
