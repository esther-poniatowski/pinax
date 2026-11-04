"""
Verification of each operation of a plan against a snapshot taken after the change.

The checks read the plan back and the library afresh; they do not trust the log of the script. A
key recorded in the plan may have been absorbed by a merge since, so every item is resolved
through `Library.survivor`.

Classes
-------
PlanChecker
    Checks every operation of a plan.

Functions
---------
check_log(plan, entries) -> list[CheckResult]
    Compare the action log of the script with the operations of the plan.
read_log(path) -> list[dict[str, Any]]
    Read the action log saved from the output of the script.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pinax.artifacts import read_json
from pinax.checks.locate import ImportLocator
from pinax.checks.model import CheckResult, Outcome, Report
from pinax.library.model import Item, Library
from pinax.library.storage import StorageIndex
from pinax.matching.confirm import TitleConfirmer
from pinax.matching.model import Verdict
from pinax.plans.model import AttachOp, ChangePlan, CorrectOp, FileOp, ImportOp
from pinax.sources.pdf import PdfReader
from pinax.text import words


class PlanChecker:
    """
    Checks every operation of a plan.

    Parameters
    ----------
    library : Library
        Snapshot taken after the change.
    storage : StorageIndex
        Index of the stored files.
    reader : PdfReader
        Extraction of the text of stored PDFs.
    confirmer : TitleConfirmer
        Confirmation of an imported record by the text of its PDF.
    pages : int
        Number of opening pages read.
    """

    def __init__(
        self,
        library: Library,
        storage: StorageIndex,
        reader: PdfReader,
        confirmer: TitleConfirmer,
        *,
        pages: int,
    ) -> None:
        self._library = library
        self._storage = storage
        self._reader = reader
        self._confirmer = confirmer
        self._pages = pages

    def check(self, plan: ChangePlan) -> Report:
        """
        Check every operation of a plan.

        Parameters
        ----------
        plan : ChangePlan
            Plan read back from its artifact.

        Returns
        -------
        Report
            One or more results per operation.
        """
        report = Report()
        located = ImportLocator(self._library, self._storage).locate(plan.imports)
        new_parents: dict[str, str] = {}
        for op in plan.imports:
            report.extend(self._import(op, located.get(op.work_id), plan, new_parents))
        for attach in plan.attachments:
            report.results.append(self._attach(attach))
        for filing in plan.filings:
            report.results.append(self._file(filing, plan))
        for correction in plan.corrections:
            report.results.append(self._correct(correction))
        return report

    def _stored_sha(self, attachment: Item) -> str:
        """SHA-256 of the stored file of an attachment, empty when the file is missing."""
        path = self._storage.stored_file(attachment)
        return self._storage.digests(path).sha256 if path else ""

    def _import(
        self,
        op: ImportOp,
        attachment: Item | None,
        plan: ChangePlan,
        new_parents: dict[str, str],
    ) -> list[CheckResult]:
        """Checks of one import: its item, its destination, its record, and its later filings."""
        if attachment is None:
            return [
                CheckResult(
                    "import", op.work_id, Outcome.FAIL, f"no attachment stores {op.staged_name}"
                )
            ]
        parent = self._library.survivor(attachment.parent) if attachment.parent else None
        if parent is None:
            return [
                CheckResult(
                    "import",
                    op.work_id,
                    Outcome.FAIL,
                    f"attachment {attachment.key} has no parent item: metadata retrieval failed",
                )
            ]
        results = [CheckResult("import", op.work_id, Outcome.PASS, f"held by {parent.key}")]
        if op.destination not in parent.collections:
            path = plan.destination(op.destination).path
            results.append(
                CheckResult("import", op.work_id, Outcome.FAIL, f"{parent.key} is not in {path}")
            )
        later = [plan.destination(key).path for key in op.also if key not in parent.collections]
        if later:
            results.append(
                CheckResult(
                    "import",
                    op.work_id,
                    Outcome.NOTE,
                    f"the next plan files {parent.key} into {", ".join(later)}",
                )
            )
        if parent.key in new_parents:
            results.append(
                CheckResult(
                    "import",
                    op.work_id,
                    Outcome.FAIL,
                    f"{parent.key} also holds {new_parents[parent.key]}",
                )
            )
        new_parents[parent.key] = op.work_id
        results.extend(self._record(op, parent, attachment))
        return results

    def _record(self, op: ImportOp, parent: Item, attachment: Item) -> list[CheckResult]:
        """Checks of the record of an imported item: title, duplicates, completeness."""
        results: list[CheckResult] = []
        path = self._storage.stored_file(attachment)
        pages = self._reader.pages(path, self._pages) if path else []
        verdict, share = self._confirmer.verdict(parent.title, pages)
        if verdict is Verdict.CONFIRMED:
            pass
        elif not pages:
            results.append(
                CheckResult(
                    "import",
                    op.work_id,
                    Outcome.NOTE,
                    f"{parent.key}: the PDF has no text layer; read its title",
                )
            )
        else:
            results.append(
                CheckResult(
                    "import",
                    op.work_id,
                    Outcome.FAIL,
                    f"{parent.key}: title `{parent.title[:60]}` does not open "
                    f"the PDF (share {share:.2f})",
                )
            )
        duplicates = self._duplicates(parent, op.doi)
        if duplicates:
            results.append(
                CheckResult(
                    "import",
                    op.work_id,
                    Outcome.FAIL,
                    f"{parent.key} duplicates {", ".join(duplicates)}",
                )
            )
        missing = [
            name
            for name, value in (
                ("date", parent.get("date")),
                ("venue", parent.venue),
                ("creators", ",".join(parent.surnames)),
            )
            if not value
        ]
        if missing:
            results.append(
                CheckResult(
                    "import",
                    op.work_id,
                    Outcome.NOTE,
                    f"{parent.key} ({parent.item_type}) lacks {", ".join(missing)}",
                )
            )
        return results

    def _duplicates(self, parent: Item, doi: str) -> list[str]:
        """Other live items sharing a DOI or the whole normalized title with an item."""
        keys = set()
        for value in (doi, *parent.dois):
            keys.update(self._library.by_doi(value) if value else [])
        title = " ".join(words(parent.title))
        if title:
            keys.update(
                item.key for item in self._library.regular() if " ".join(words(item.title)) == title
            )
        keys.discard(parent.key)
        return sorted(keys)

    def _attach(self, op: AttachOp) -> CheckResult:
        """Check that the item holds the attached file."""
        item = self._library.survivor(op.item)
        if item is None:
            return CheckResult("attach", op.item, Outcome.FAIL, "item missing")
        pdfs = self._library.pdfs(item.key)
        if not pdfs:
            return CheckResult("attach", op.item, Outcome.FAIL, f"{item.key} has no PDF")
        same = any(
            pdf.get("md5") == op.file.md5 or self._stored_sha(pdf) == op.file.sha256 for pdf in pdfs
        )
        if same:
            return CheckResult("attach", op.item, Outcome.PASS, f"{item.key} holds the file")
        return CheckResult("attach", op.item, Outcome.NOTE, f"{item.key} holds another PDF")

    def _file(self, op: FileOp, plan: ChangePlan) -> CheckResult:
        """Check that the item lies directly in its destination."""
        path = plan.destination(op.destination).path
        item = self._library.survivor(op.item)
        if item is None:
            return CheckResult("file", op.item, Outcome.FAIL, "item missing")
        if op.destination in item.collections:
            return CheckResult("file", op.item, Outcome.PASS, f"{item.key} in {path}")
        return CheckResult("file", op.item, Outcome.FAIL, f"{item.key} not in {path}")

    def _correct(self, op: CorrectOp) -> CheckResult:
        """Check that the type, fields, carried fields and creators hold their planned values."""
        item = self._library.survivor(op.item)
        if item is None:
            return CheckResult("correct", op.item, Outcome.FAIL, "item missing")
        problems = []
        if op.item_type and item.item_type != op.item_type:
            problems.append(f"type {item.item_type}")
        problems += [
            f"{name}={item.get(name)!r}"
            for name, value in op.fields.items()
            if item.get(name) != value
        ]
        problems += [f"{target} empty" for target in op.carry.values() if not item.get(target)]
        problems += [
            f"{name} lost"
            for name in op.preserve
            if not item.get(name) and f"{name}:" not in item.get("extra")
        ]
        if op.creators is not None:
            expected = tuple(creator.last_name for creator in op.creators)
            if item.surnames != expected:
                problems.append(f"creators {", ".join(item.surnames)}")
        if problems:
            return CheckResult("correct", op.item, Outcome.FAIL, "; ".join(problems))
        return CheckResult("correct", op.item, Outcome.PASS, f"{item.key} {item.item_type}")


def check_log(plan: ChangePlan, entries: Sequence[Mapping[str, Any]]) -> list[CheckResult]:
    """
    Compare the action log of the script with the operations of the plan.

    Parameters
    ----------
    plan : ChangePlan
        Plan of the script.
    entries : Sequence[Mapping[str, Any]]
        Records returned by the script.

    Returns
    -------
    list[CheckResult]
        A failure for each operation without a `done` or `skip` record, and a note for each
        skipped attachment, whose item held a PDF when the script ran. A filing is recorded with
        the key of its collection, since one item may be filed into several destinations.
    """
    logged = {
        (str(e.get("op")), str(e.get("item")), str(e.get("collection") or "")): str(
            e.get("outcome")
        )
        for e in entries
    }
    expected = [("attach", op.item, "") for op in plan.attachments]
    expected += [("file", op.item, op.destination) for op in plan.filings]
    expected += [("correct", op.item, "") for op in plan.corrections]
    results = []
    for operation, item, collection in expected:
        outcome = logged.get((operation, item, collection))
        if outcome not in ("done", "skip"):
            results.append(CheckResult("log", item, Outcome.FAIL, f"no record of {operation}"))
        elif operation == "attach" and outcome == "skip":
            results.append(
                CheckResult("log", item, Outcome.NOTE, "attachment skipped: a PDF existed")
            )
    return results


def read_log(path: Path) -> list[dict[str, Any]]:
    """
    Read the action log saved from the output of the script.

    Parameters
    ----------
    path : Path
        JSON file holding the list returned by the script.

    Returns
    -------
    list[dict[str, Any]]
        Records of the log.
    """
    data = read_json(path)
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]
