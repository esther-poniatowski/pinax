"""Tests of the plan builder, the corrections, the staging and the worklist."""

from pathlib import Path

import pytest

from conftest import SourceTree, api_collection, api_item, library, pdf_attachment, pdf_bytes
from pinax.errors import ConfigError, PlanError
from pinax.library.model import Library
from pinax.matching.model import Match, Method, Status, Verdict
from pinax.plans.builder import PlanBuilder
from pinax.plans.corrections import load_corrections
from pinax.plans.model import ChangePlan
from pinax.plans.staging import stage
from pinax.plans.worklist import render_worklist
from pinax.sources.inventory import Inventory

COLLECTIONS = [
    api_collection("REVIEW01", "review"),
    api_collection("BACKGR01", "background", "REVIEW01"),
    api_collection("ELSEWH01", "elsewhere"),
]


def _library() -> Library:
    return library(
        [
            api_item("NOPDF001", title="An item without PDF", collections=["ELSEWH01"]),
            api_item("HASPDF01", title="An item with a PDF", collections=["BACKGR01"]),
            pdf_attachment("ATT00001", "HASPDF01", "a.pdf"),
            api_item("PREPUB01", title="The published version"),
        ],
        COLLECTIONS,
    )


def _inventory(sources: SourceTree) -> Inventory:
    sources.add("a/small.pdf", pdf_bytes("s"))
    sources.add("b/large.pdf", pdf_bytes("a larger copy of the same work"))
    sources.add("a/haspdf.pdf", pdf_bytes("h"))
    sources.add("a/preprint.pdf", pdf_bytes("p"))
    sources.add("a/new.pdf", pdf_bytes("n"), ["doi:10.5555/new"])
    sources.add("b/new.pdf", pdf_bytes("same name, other content"))
    sources.add("a/slides.pptx", b"slides")
    return sources.inventory()


def _matches(inventory: Inventory) -> list[Match]:
    status = {
        "small.pdf": (Status.MATCHED, "NOPDF001"),
        "large.pdf": (Status.MATCHED, "NOPDF001"),
        "haspdf.pdf": (Status.MATCHED, "HASPDF01"),
        "preprint.pdf": (Status.PREPRINT_OF, "PREPUB01"),
    }
    matches = []
    for content in inventory:
        found = status.get(content.first.name)
        if found:
            matches.append(
                Match(content.sha256, found[0], found[1], Method.NAME, Verdict.CONFIRMED)
            )
        else:
            matches.append(Match(content.sha256, Status.ABSENT))
    return matches


def test_plan_attaches_files_and_imports_absent_works(sources: SourceTree) -> None:
    inventory = _inventory(sources)
    plan = PlanBuilder(_library(), inventory, "BACKGR01", "REVIEW01").build(_matches(inventory))
    assert plan.destination.path == "review/background"
    assert [(op.item, Path(op.file.path).name) for op in plan.attachments] == [
        ("NOPDF001", "large.pdf")
    ]
    filings = {op.item: op for op in plan.filings}
    assert sorted(filings) == ["NOPDF001", "PREPUB01"]
    assert filings["NOPDF001"].current == ("elsewhere",)
    assert sorted(op.staged_name for op in plan.imports) == ["new.pdf", "new_2.pdf"]
    assert [op.reason for op in plan.skipped] == ["no PDF file holds the work"]
    assert ChangePlan.from_json(plan.to_json()) == plan


def test_plan_refuses_matches_left_to_check(sources: SourceTree) -> None:
    inventory = _inventory(sources)
    matches = _matches(inventory)
    matches[0] = Match(matches[0].sha256, Status.CHECK, "NOPDF001", Method.NAME, Verdict.CHECK)
    with pytest.raises(PlanError, match="await a check"):
        PlanBuilder(_library(), inventory, "BACKGR01", "REVIEW01").build(matches)


def test_plan_refuses_a_missing_destination(sources: SourceTree) -> None:
    with pytest.raises(PlanError, match="create it in Zotero first"):
        PlanBuilder(_library(), _inventory(sources), "NONE0001", "REVIEW01")


def test_corrections_are_loaded_and_validated(tmp_path: Path, sources: SourceTree) -> None:
    path = tmp_path / "corrections.yml"
    path.write_text(
        "corrections:\n"
        "  - item: NOPDF001\n"
        "    type: bookSection\n"
        "    fields: {date: '2012'}\n"
        "    creators: [{lastName: Doe, firstName: Jane}, {lastName: Some Institute}]\n"
        "    carry: {publicationTitle: bookTitle}\n"
        "    preserve: [DOI]\n",
        encoding="utf-8",
    )
    corrections = load_corrections(path)
    assert corrections[0].creators is not None and len(corrections[0].creators) == 2
    inventory = _inventory(sources)
    plan = PlanBuilder(_library(), inventory, "BACKGR01", "REVIEW01").build(
        _matches(inventory), corrections
    )
    assert plan.corrections[0].carry == {"publicationTitle": "bookTitle"}
    path.write_text("corrections:\n  - {item: NONE0001, fields: {date: '1'}}\n", encoding="utf-8")
    with pytest.raises(PlanError, match="not in the library"):
        PlanBuilder(_library(), inventory, "BACKGR01", "REVIEW01").build(
            _matches(inventory), load_corrections(path)
        )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("corrections:\n  - {fields: {}}\n", "must name an `item`"),
        ("corrections:\n  - {item: A, colour: red}\n", "unknown keys"),
        ("corrections:\n  - {item: A}\n  - {item: A}\n", "corrected twice"),
        ("corrections:\n  - {item: A, creators: [{firstName: X}]}\n", "lastName"),
    ],
)
def test_invalid_corrections_are_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "corrections.yml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_corrections(path)


def test_staging_copies_and_verifies_and_refuses_a_used_folder(
    tmp_path: Path, sources: SourceTree
) -> None:
    inventory = _inventory(sources)
    plan = PlanBuilder(_library(), inventory, "BACKGR01", "REVIEW01").build(_matches(inventory))
    folder = tmp_path / "staged"
    assert stage(plan, folder) == 2
    assert sorted(p.name for p in folder.iterdir()) == ["new.pdf", "new_2.pdf"]
    with pytest.raises(PlanError, match="not empty"):
        stage(plan, folder)


def test_worklist_lists_every_operation(sources: SourceTree, tmp_path: Path) -> None:
    inventory = _inventory(sources)
    plan = PlanBuilder(_library(), inventory, "BACKGR01", "REVIEW01").build(_matches(inventory))
    text = render_worklist(plan, tmp_path / "staged dir")
    assert "## Import (2)" in text and "## Attach a PDF (1)" in text
    assert "## Not imported (1)" in text
    assert "open '" in text and "staged dir'" in text
