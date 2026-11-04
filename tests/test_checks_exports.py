"""Tests of the checks of a plan after the change, and of the evidence file and reference lists."""

from pathlib import Path

import yaml

from conftest import (
    FakeReader,
    SourceTree,
    Storage,
    api_collection,
    api_item,
    library,
    md5_of,
    pdf_attachment,
    pdf_bytes,
)
from pinax.checks.model import Outcome
from pinax.checks.operations import PlanChecker, check_log
from pinax.exports.evidence import EvidenceBuilder, Route, render_evidence
from pinax.exports.references import render_references, shared_keys
from pinax.hashing import digest_file
from pinax.library.model import Library
from pinax.library.storage import StorageIndex
from pinax.matching.confirm import TitleConfirmer
from pinax.matching.model import Match, Method, Status, Verdict
from pinax.plans.model import (
    AttachOp,
    ChangePlan,
    CorrectOp,
    Destination,
    FileOp,
    FileRef,
    ImportOp,
)

DEST = "DEST0001"
OTHER_DEST = "DEST0002"
DESTINATIONS = (
    Destination(DEST, "background", "background", DEST, "background"),
    Destination(OTHER_DEST, "methods", "methods", OTHER_DEST, "methods"),
)
TITLE = "Temporal dynamics of attention in a recurrent network model"


def _ref(path: Path) -> FileRef:
    digests = digest_file(path)
    return FileRef(str(path), digests.sha256, digests.md5, digests.size)


def _import(
    work_id: str, path: Path, members: tuple[str, ...] = (), also: tuple[str, ...] = ()
) -> ImportOp:
    ref = _ref(path)
    return ImportOp(work_id, "", ref, path.name, members or (ref.sha256,), DEST, also)


def _checker(lib: Library, storage: Storage, reader: FakeReader) -> PlanChecker:
    return PlanChecker(lib, StorageIndex(storage.root), reader, TitleConfirmer(8, 0.5), pages=2)


def _results(report_results: list[object], target: str) -> list[tuple[str, str]]:
    return [
        (r.outcome.value, r.detail)  # type: ignore[attr-defined]
        for r in report_results
        if r.target == target  # type: ignore[attr-defined]
    ]


def test_checks_of_imports(tmp_path: Path, storage: Storage) -> None:
    reader = FakeReader()
    files = {}
    for name in ("good", "merged", "alone", "missing", "misread"):
        data = pdf_bytes(name)
        files[name] = tmp_path / f"{name}.pdf"
        files[name].write_bytes(data)
        reader.texts[data] = [f"{TITLE}. Abstract."]
    storage.store("ATTGOOD1", "renamed.pdf", files["good"].read_bytes())
    storage.store("ATTMERG1", "x.pdf", files["merged"].read_bytes())
    storage.store("ATTALON1", "y.pdf", files["alone"].read_bytes())
    storage.store("ATTMISR1", "z.pdf", files["misread"].read_bytes())
    lib = library(
        [
            api_item(
                "GOOD0001",
                title=TITLE,
                date="2004",
                creators=["Doe"],
                collections=[DEST],
                publicationTitle="J",
            ),
            pdf_attachment(
                "ATTGOOD1", "GOOD0001", "renamed.pdf", md5=md5_of(files["good"].read_bytes())
            ),
            api_item("OLDMERG1", deleted=True),
            api_item("NEWMERG1", title=TITLE + " bis", replaces=["OLDMERG1"]),
            pdf_attachment("ATTMERG1", "OLDMERG1", "x.pdf"),
            pdf_attachment("ATTALON1", None, "y.pdf"),
            api_item(
                "MISREAD1",
                title="Bachelor thesis March 8, 2012",
                collections=[DEST],
                DOI="10.5555/d",
            ),
            pdf_attachment("ATTMISR1", "MISREAD1", "z.pdf"),
            api_item("EARLIER1", title="Something else", DOI="10.5555/d"),
        ],
        [api_collection(DEST, "background")],
    )
    imports = [_import(name, files[name]) for name in files]
    imports[0] = _import("good", files["good"], also=(OTHER_DEST,))
    plan = ChangePlan(DESTINATIONS, imports=tuple(imports))
    results = _checker(lib, storage, reader).check(plan).results
    assert _results(results, "good") == [
        ("pass", "held by GOOD0001"),
        ("note", "the next plan files GOOD0001 into methods"),
    ]
    merged = _results(results, "merged")
    assert ("pass", "held by NEWMERG1") in merged
    assert ("fail", "NEWMERG1 is not in background") in merged
    assert ("note", "NEWMERG1 (journalArticle) lacks date, venue, creators") in merged
    assert _results(results, "alone")[0][0] == "fail"
    assert "metadata retrieval failed" in _results(results, "alone")[0][1]
    assert _results(results, "missing") == [("fail", "no attachment stores missing.pdf")]
    misread = [detail for outcome, detail in _results(results, "misread") if outcome == "fail"]
    assert any("does not open the PDF" in detail for detail in misread)
    assert "MISREAD1 duplicates EARLIER1" in misread


def test_checks_of_attachments_filings_and_corrections(tmp_path: Path, storage: Storage) -> None:
    source = tmp_path / "s.pdf"
    source.write_bytes(pdf_bytes("attached"))
    storage.store("ATTSAME1", "s.pdf", source.read_bytes())
    storage.store("ATTOTHR1", "o.pdf", pdf_bytes("other"))
    lib = library(
        [
            api_item("SAME0001", collections=[DEST]),
            pdf_attachment("ATTSAME1", "SAME0001", "s.pdf"),
            api_item("OTHER001"),
            pdf_attachment("ATTOTHR1", "OTHER001", "o.pdf"),
            api_item("NONE0001"),
            api_item(
                "CHAP0001", "bookSection", bookTitle="Book", extra="DOI: 10.5555/c", date="2001"
            ),
            api_item("WRONG001", "journalArticle"),
        ]
    )
    ref = _ref(source)
    plan = ChangePlan(
        DESTINATIONS,
        attachments=tuple(AttachOp(k, "", "", ref) for k in ("SAME0001", "OTHER001", "NONE0001")),
        filings=(
            FileOp("SAME0001", "", "", DEST),
            FileOp("SAME0001", "", "", OTHER_DEST),
            FileOp("NONE0001", "", "", DEST),
        ),
        corrections=(
            CorrectOp(
                "CHAP0001",
                "bookSection",
                {"date": "2001"},
                carry={"publicationTitle": "bookTitle"},
                preserve=("DOI",),
            ),
            CorrectOp("WRONG001", "thesis"),
        ),
    )
    results = _checker(lib, storage, FakeReader()).check(plan).results
    outcomes = {(r.operation, r.target): r.outcome for r in results if "methods" not in r.detail}
    assert ("fail", "SAME0001 not in methods") in _results(results, "SAME0001")
    assert outcomes[("attach", "SAME0001")] is Outcome.PASS
    assert outcomes[("attach", "OTHER001")] is Outcome.NOTE
    assert outcomes[("attach", "NONE0001")] is Outcome.FAIL
    assert outcomes[("file", "SAME0001")] is Outcome.PASS
    assert outcomes[("file", "NONE0001")] is Outcome.FAIL
    assert outcomes[("correct", "CHAP0001")] is Outcome.PASS
    assert outcomes[("correct", "WRONG001")] is Outcome.FAIL
    log = [
        {"op": "attach", "item": "SAME0001", "outcome": "done"},
        {"op": "attach", "item": "OTHER001", "outcome": "skip"},
        {"op": "file", "item": "SAME0001", "outcome": "skip", "collection": DEST},
        {"op": "file", "item": "SAME0001", "outcome": "done", "collection": OTHER_DEST},
    ]
    logged = {(r.target, r.outcome) for r in check_log(plan, log)}
    assert ("OTHER001", Outcome.NOTE) in logged
    assert ("NONE0001", Outcome.FAIL) in logged
    assert ("SAME0001", Outcome.FAIL) not in logged
    unrecorded = check_log(plan, log[:-1])
    assert [(r.target, r.outcome) for r in unrecorded if r.target == "SAME0001"] == [
        ("SAME0001", Outcome.FAIL)
    ]


def test_evidence_routes_and_reference_lists(sources: SourceTree, storage: Storage) -> None:
    imported_a = sources.add("f1/new-a.pdf", pdf_bytes("new a"), ["doi:10.5555/w"])
    sources.add("f2/new-b.pdf", pdf_bytes("new b, same work"), ["doi:10.5555/w"])
    sources.add("f1/old.pdf", pdf_bytes("old"))
    sources.add("f1/preprint.pdf", pdf_bytes("pre"))
    sources.add("f2/nokey.pdf", pdf_bytes("nokey"))
    deleted_copy = sources.add("f2/deleted-copy.pdf", pdf_bytes("deleted copy"))
    sources.add("f2/nothing.pdf", pdf_bytes("nothing"))
    inventory = sources.inventory()
    sha = {f.name: f.sha256 for f in inventory.files}
    storage.store("ATTNEW01", "Doe - 2004.pdf", imported_a.read_bytes())
    lib = library(
        [
            api_item("ABSORB01", deleted=True),
            api_item("NEWITEM1", citationKey="doe2004", replaces=["ABSORB01"]),
            pdf_attachment("ATTNEW01", "ABSORB01", "Doe - 2004.pdf"),
            api_item("OLDITEM1", citationKey="smith1999"),
            api_item("PUBLISH1", citationKey="roe2010"),
            api_item("NOKEY001"),
            api_item("SAMEWRK1", citationKey="doe2004"),
        ]
    )
    plan = ChangePlan(
        DESTINATIONS,
        imports=(
            _import("doi:10.5555/w", imported_a, (sha["new-a.pdf"], sha["new-b.pdf"])),
            _import("sha256:deleted", deleted_copy),
        ),
    )
    matches = [
        Match(sha["old.pdf"], Status.MATCHED, "OLDITEM1", Method.SAME_FILE, Verdict.IDENTICAL),
        Match(sha["preprint.pdf"], Status.PREPRINT_OF, "PUBLISH1", Method.RESOLUTION),
        Match(sha["nokey.pdf"], Status.MATCHED, "NOKEY001", Method.NAME, Verdict.CONFIRMED),
        Match(sha["deleted-copy.pdf"], Status.MATCHED, "SAMEWRK1", Method.DOI, Verdict.CONFIRMED),
        Match(sha["nothing.pdf"], Status.ABSENT),
    ]
    rows = EvidenceBuilder(lib, StorageIndex(storage.root), [plan]).build(inventory, matches)
    by_name = {row.name: row for row in rows}
    assert (by_name["new-a.pdf"].route, by_name["new-a.pdf"].item) == (Route.IMPORTED, "NEWITEM1")
    assert (by_name["new-b.pdf"].route, by_name["new-b.pdf"].citation_key) == (
        Route.IMPORTED,
        "doe2004",
    )
    assert (by_name["deleted-copy.pdf"].route, by_name["deleted-copy.pdf"].item) == (
        Route.IMPORTED,
        "SAMEWRK1",
    )
    assert by_name["old.pdf"].route is Route.MATCHED
    assert by_name["preprint.pdf"].route is Route.PREPRINT_OF
    assert by_name["nokey.pdf"].route is Route.UNRESOLVED
    assert by_name["nothing.pdf"].route is Route.UNRESOLVED
    text = render_evidence(rows, "# header\n")
    entries = [line for line in text.splitlines() if line.startswith("- {")]
    assert len(entries) == len(inventory.files)
    evidence = yaml.safe_load(text)["sources"]
    assert list(evidence[0]) == ["sha256", "folder", "file", "route", "zotero_item", "citation_key"]
    assert [(e["sha256"], e["file"]) for e in evidence] == [(r.sha256, r.name) for r in rows]
    nothing = next(entry for entry in evidence if entry["file"] == "nothing.pdf")
    assert (nothing["route"], nothing["zotero_item"], nothing["citation_key"]) == (
        "unresolved",
        None,
        None,
    )
    references = yaml.safe_load(render_references(rows, "# header\n"))
    assert references["folders"]["f1"] == ["doe2004", "roe2010", "smith1999"]
    assert references["unresolved"] == ["f2/nokey.pdf", "f2/nothing.pdf"]
    assert shared_keys(rows) == {"doe2004": ["NEWITEM1", "SAMEWRK1"]}
