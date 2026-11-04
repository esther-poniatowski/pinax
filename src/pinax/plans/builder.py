"""
Construction of a change plan from the matches.

Classes
-------
PlanBuilder
    Builds the plan of one reconciliation from an inventory, its matches and the library.
"""

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from pinax.config import Target
from pinax.errors import PlanError
from pinax.library.model import Item, Library
from pinax.matching.confirm import TitleConfirmer
from pinax.matching.model import Match, RecordMatch, Status, Verdict
from pinax.matching.works import Work, group_works
from pinax.plans.model import (
    AttachOp,
    ChangePlan,
    CorrectOp,
    CreateOp,
    Destination,
    FileOp,
    FileRef,
    ImportOp,
    SkippedWork,
)
from pinax.plans.targets import TargetMap
from pinax.records.items import connector_item
from pinax.records.model import Record
from pinax.records.works import RecordWork, group_records
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
    targets : Sequence[Target]
        Folders of the sources and their collections.
    confirmer : TitleConfirmer
        Confirmation of a title by the first pages of a PDF, which tells whether an absent PDF
        holds the work of a record to create.

    Raises
    ------
    PlanError
        If a collection of a target is missing or ambiguous. A missing collection is created by the
        researcher in Zotero; the plan never creates one.
    """

    def __init__(
        self,
        library: Library,
        inventory: Inventory,
        targets: Sequence[Target],
        *,
        confirmer: TitleConfirmer,
    ) -> None:
        self._library = library
        self._inventory = inventory
        self._targets = TargetMap(library, targets)
        self._confirmer = confirmer

    def _claims(self, record: Record, pdfs: Sequence[Content], taken: set[str]) -> tuple[str, ...]:
        """
        Absent PDFs holding the work of a record: those whose first pages confirm its title, and
        those carrying its DOI unless their pages reject its title, since a DOI on a first page
        can belong to a cited work.
        """
        found = []
        for content in pdfs:
            if content.sha256 in taken:
                continue
            verdict, _ = self._confirmer.verdict(record.title, content.pages)
            same_doi = bool(record.doi) and content.doi == record.doi
            if verdict is Verdict.CONFIRMED or (same_doi and verdict is not Verdict.REJECTED):
                found.append(content.sha256)
        return tuple(found)

    def _destinations(self, folders: Iterable[str]) -> list[Destination]:
        """Distinct destinations of some folders of the sources, in folder order."""
        return list(dict.fromkeys(self._targets.destination(folder) for folder in folders))

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

    def _filings(
        self, matches: Sequence[Match], records: Sequence[RecordMatch], works: dict[str, RecordWork]
    ) -> list[FileOp]:
        """Matched and preprint items outside the scope of a destination of their folders."""
        held: list[tuple[str, Iterable[str]]] = [
            (match.item, (f.folder for f in self._inventory.contents[match.sha256].files))
            for match in matches
            if match.status in (Status.MATCHED, Status.PREPRINT_OF)
        ]
        held += [
            (match.item, works[match.identity].folders)
            for match in records
            if match.status in (Status.MATCHED, Status.PREPRINT_OF)
        ]
        pairs: dict[tuple[str, str], Destination] = {}
        for matched, folders in held:
            key = self._item(matched).key
            for dest in self._destinations(folders):
                pairs.setdefault((key, dest.key), dest)
        ops = []
        for (key, _), dest in pairs.items():
            item = self._library.items[key]
            if self._library.in_subtree(item, dest.scope):
                continue
            current = tuple(self._library.collection_path(c) for c in item.collections)
            ops.append(FileOp(key, item.citation_key, item.title, dest.key, current))
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
            pdf = next(f for f in representative.files if f.is_pdf)
            destination = self._targets.destination(pdf.folder)
            others = self._destinations(f.folder for c in work.members for f in c.files)
            imports.append(
                ImportOp(
                    work_id=work.work_id,
                    doi=work.doi,
                    file=self._file_ref(representative),
                    staged_name=_unique_name(pdf.name, taken),
                    members=tuple(c.sha256 for c in work.members),
                    destination=destination.key,
                    also=tuple(d.key for d in others if d.key != destination.key),
                )
            )
        return imports, skipped

    def _creations(
        self, records: Sequence[RecordMatch], works: dict[str, RecordWork], absent: list[Content]
    ) -> tuple[list[CreateOp], list[SkippedWork], set[str]]:
        """
        One creation per record work that no item holds, from its record with the most fields.

        A work that only DOIs describe is skipped, since a creation needs metadata. The absent PDFs
        holding the work of a creation, by `_claims`, are returned as claimed: the plan does not
        import them, so that one work yields one item, and the next plan attaches them to the
        created item.
        """
        pdfs = [content for content in absent if any(file.is_pdf for file in content.files)]
        creations: list[CreateOp] = []
        skipped: list[SkippedWork] = []
        claimed: set[str] = set()
        for match in records:
            if match.status is not Status.ABSENT:
                continue
            work = works[match.identity]
            record = work.best
            if not record.has_metadata:
                reason = "the records hold only a DOI, from which no item can be created"
                skipped.append(SkippedWork(work.identity, reason, work.refs))
                continue
            first, *others = self._destinations(work.folders)
            files = self._claims(record, pdfs, claimed)
            claimed.update(files)
            creations.append(
                CreateOp(
                    identity=work.identity,
                    title=record.title,
                    doi=record.doi,
                    item=connector_item(record),
                    destination=first.key,
                    records=work.refs,
                    also=tuple(dest.key for dest in others),
                    files=files,
                )
            )
        return creations, skipped, claimed

    def _corrections(self, corrections: Sequence[CorrectOp]) -> list[CorrectOp]:
        """Corrections, after checking that each item is live."""
        missing = [op.item for op in corrections if self._library.get_live(op.item) is None]
        if missing:
            raise PlanError(f"corrected items not in the library: {", ".join(missing)}")
        return list(corrections)

    def build(
        self,
        matches: Sequence[Match],
        corrections: Sequence[CorrectOp] = (),
        records: Sequence[RecordMatch] = (),
    ) -> ChangePlan:
        """
        Build the plan.

        Parameters
        ----------
        matches : Sequence[Match]
            Matches of every content of the inventory.
        corrections : Sequence[CorrectOp]
            Corrections of item records.
        records : Sequence[RecordMatch]
            Matches of every record work of the inventory.

        Returns
        -------
        ChangePlan
            Creations of the absent record works; imports of the other absent works, each into
            the destination of its imported file; attachments to matched items without a PDF;
            filings of matched items outside the scope of each destination of their folders; and
            the corrections. A preprint never becomes the PDF of the published item, so preprint
            matches only lead to filings.

        Raises
        ------
        PlanError
            If a match still awaits a check, a corrected or matched item is missing, or a record
            match names a work absent from the inventory.
        """
        pending = [
            str(self._inventory.contents[m.sha256].first.relative)
            for m in matches
            if m.status is Status.CHECK
        ]
        pending += [m.refs[0] for m in records if m.status is Status.CHECK]
        if pending:
            raise PlanError(
                "matches await a check; resolve them before planning:\n  " + "\n  ".join(pending)
            )
        works = {work.identity: work for work in group_records(self._inventory.records)}
        unknown = [m.identity for m in records if m.identity not in works]
        if unknown:
            raise PlanError(f"record matches name works absent from the inventory: {unknown[0]}")
        absent = [self._inventory.contents[m.sha256] for m in matches if m.status is Status.ABSENT]
        creations, unborn, claimed = self._creations(records, works, absent)
        imports, skipped = self._imports(group_works(c for c in absent if c.sha256 not in claimed))
        return ChangePlan(
            destinations=self._targets.destinations,
            imports=tuple(imports),
            attachments=tuple(self._attachments(matches)),
            filings=tuple(self._filings(matches, records, works)),
            corrections=tuple(self._corrections(corrections)),
            skipped=tuple(skipped + unborn),
            creations=tuple(creations),
        )
