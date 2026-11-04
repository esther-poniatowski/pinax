"""Tests of the plan builder, the corrections, the staging and the worklist."""

from pathlib import Path

import pytest

from conftest import (
    SourceTree,
    api_collection,
    api_item,
    by_path,
    library,
    pdf_attachment,
    pdf_bytes,
    target,
)
from pinax.config import Target
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
    api_collection("METHOD01", "methods", "REVIEW01"),
    api_collection("ELSEWH01", "elsewhere"),
]
ONE_TARGET = [target(".", "BACKGR01", "REVIEW01")]


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
    plan = PlanBuilder(_library(), inventory, ONE_TARGET).build(_matches(inventory))
    assert [d.path for d in plan.destinations] == ["review/background"]
    assert plan.destinations[0].scope_path == "review"
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
        PlanBuilder(_library(), inventory, ONE_TARGET).build(matches)


def test_each_folder_files_into_its_own_destination(sources: SourceTree) -> None:
    inventory = _inventory(sources)
    targets = [target("a", "BACKGR01", "REVIEW01"), Target("b", by_path("review/methods"), None)]
    plan = PlanBuilder(_library(), inventory, targets).build(_matches(inventory))
    assert [d.key for d in plan.destinations] == ["BACKGR01", "METHOD01"]
    filings = sorted((op.item, op.destination) for op in plan.filings)
    assert filings == [("NOPDF001", "BACKGR01"), ("NOPDF001", "METHOD01"), ("PREPUB01", "BACKGR01")]
    by_name = {Path(op.file.path).parent.name: op for op in plan.imports}
    assert by_name["a"].destination == "BACKGR01" and by_name["b"].destination == "METHOD01"
    assert ChangePlan.from_json(plan.to_json()) == plan


def test_a_work_spanning_two_targets_is_imported_once(sources: SourceTree) -> None:
    sources.add("a/new.pdf", pdf_bytes("n"), ["doi:10.5555/new"])
    sources.add(
        "b/larger.pdf", pdf_bytes("the larger copy, which is imported"), ["doi:10.5555/new"]
    )
    inventory = sources.inventory()
    targets = [target("a", "BACKGR01"), target("b", "METHOD01")]
    matches = [Match(content.sha256, Status.ABSENT) for content in inventory]
    plan = PlanBuilder(_library(), inventory, targets).build(matches)
    assert [(op.staged_name, op.destination, op.also) for op in plan.imports] == [
        ("larger.pdf", "METHOD01", ("BACKGR01",))
    ]


def test_the_deepest_target_folder_decides(sources: SourceTree) -> None:
    sources.add("a/deep/x.pdf", pdf_bytes("x"))
    inventory = sources.inventory()
    targets = [target(".", "ELSEWH01"), target("a/deep", "METHOD01")]
    matches = [Match(content.sha256, Status.ABSENT) for content in inventory]
    plan = PlanBuilder(_library(), inventory, targets).build(matches)
    assert [op.destination for op in plan.imports] == ["METHOD01"]


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        ([target(".", "NONE0001")], "create it in Zotero first"),
        ([Target(".", by_path("review/absent"), None)], "no collection has the path"),
        ([target("a", "BACKGR01", "REVIEW01"), target("b", "BACKGR01")], "two scopes"),
    ],
)
def test_plan_refuses_missing_and_conflicting_collections(
    sources: SourceTree, targets: list[Target], message: str
) -> None:
    with pytest.raises(PlanError, match=message):
        PlanBuilder(_library(), _inventory(sources), targets)


def test_plan_refuses_an_ambiguous_path(sources: SourceTree) -> None:
    lib = library([], [*COLLECTIONS, api_collection("TWIN0001", "elsewhere")])
    with pytest.raises(PlanError, match="several collections have the path elsewhere"):
        PlanBuilder(lib, _inventory(sources), [Target(".", by_path("elsewhere"), None)])


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
    plan = PlanBuilder(_library(), inventory, ONE_TARGET).build(_matches(inventory), corrections)
    assert plan.corrections[0].carry == {"publicationTitle": "bookTitle"}
    path.write_text("corrections:\n  - {item: NONE0001, fields: {date: '1'}}\n", encoding="utf-8")
    with pytest.raises(PlanError, match="not in the library"):
        PlanBuilder(_library(), inventory, ONE_TARGET).build(
            _matches(inventory), load_corrections(path)
        )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("corrections:\n  - {fields: {}}\n", "must name an `item`"),
        ("corrections:\n  - {item: A, colour: red}\n", "unknown keys"),
        ("corrections:\n  - {item: A}\n  - {item: A}\n", "corrected twice"),
        ("corrections:\n  - {item: A, creators: [{firstName: X}]}\n", "lastName"),
        ("correction:\n  - {item: A}\n", "only the key `corrections`"),
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
    plan = PlanBuilder(_library(), inventory, ONE_TARGET).build(_matches(inventory))
    folder = tmp_path / "staged"
    assert stage(plan, folder) == 2
    assert sorted(str(p.relative_to(folder)) for p in folder.rglob("*.pdf")) == [
        "BACKGR01 background/new.pdf",
        "BACKGR01 background/new_2.pdf",
    ]
    with pytest.raises(PlanError, match="not empty"):
        stage(plan, folder)


def test_worklist_lists_every_operation(sources: SourceTree, tmp_path: Path) -> None:
    inventory = _inventory(sources)
    plan = PlanBuilder(_library(), inventory, ONE_TARGET).build(_matches(inventory))
    text = render_worklist(plan, tmp_path / "staged dir")
    assert "## Import (2)" in text and "## Attach a PDF (1)" in text
    assert "## Not imported (1)" in text
    assert "open '" in text and "staged dir'" in text
    assert "| `review/background` | `BACKGR01` | `review` | BACKGR01 background |" in text
