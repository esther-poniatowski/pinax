"""Tests of the inventory, the routes of the matching, the confirmation and the resolutions."""

import pytest

from conftest import SourceTree, Storage, api_item, library, pdf_attachment, pdf_bytes
from pinax.config import MatchingConfig
from pinax.errors import ArtifactError, ConfigError
from pinax.library.model import Library
from pinax.library.storage import StorageIndex
from pinax.matching.matcher import Matcher
from pinax.matching.model import Match, Method, Status, Verdict
from pinax.matching.resolutions import Resolutions, load_resolutions
from pinax.matching.works import group_works
from pinax.sources.inventory import Inventory

TITLE = "Temporal dynamics of attention in a recurrent network model"
OTHER = "Spectral bounds on the learning dynamics of deep linear networks"


def _match(
    sources: SourceTree,
    lib: Library,
    storage: Storage | None = None,
    resolutions: str | None = None,
) -> dict[str, Match]:
    inventory = sources.inventory()
    stored = StorageIndex(storage.root).by_sha256(c.size for c in inventory) if storage else {}
    loaded = Resolutions()
    if resolutions is not None:
        path = sources.root.parent / "resolutions.yml"
        path.write_text(resolutions, encoding="utf-8")
        loaded = load_resolutions(path, inventory)
    matcher = Matcher.build(lib, stored, MatchingConfig(), loaded)
    return {inventory.contents[m.sha256].first.name: m for m in matcher.match_all(inventory)}


def test_inventory_groups_identical_files_and_reads_doi(sources: SourceTree) -> None:
    data = pdf_bytes("one")
    sources.add("a/2004_smith_model.pdf", data, ["Header doi:10.5555/ABC.1 text"])
    sources.add("b/copy.pdf", data)
    sources.add("b/notes.txt", b"plain text")
    sources.add("b/.DS_Store", b"ignored")
    inventory = sources.inventory()
    assert [f.name for f in inventory.files] == ["2004_smith_model.pdf", "copy.pdf", "notes.txt"]
    assert len(inventory.contents) == 2
    content = inventory.contents[inventory.files[0].sha256]
    assert content.folders == ("a", "b")
    assert content.doi == "10.5555/abc.1"
    assert inventory.files[0].year == "2004"
    assert Inventory.from_json(inventory.to_json()).contents.keys() == inventory.contents.keys()


def test_same_file_is_identical_even_without_text(sources: SourceTree, storage: Storage) -> None:
    data = pdf_bytes("stored")
    sources.add("a/renamed.pdf", data)
    storage.store("ATT00001", "Smith - 2004 - Something.pdf", data)
    lib = library([api_item("ITEM0001", title=TITLE), pdf_attachment("ATT00001", "ITEM0001", "x")])
    match = _match(sources, lib, storage)["renamed.pdf"]
    assert (match.status, match.item, match.verdict) == (
        Status.MATCHED,
        "ITEM0001",
        Verdict.IDENTICAL,
    )


def test_same_file_of_a_merged_item_resolves_to_the_survivor(
    sources: SourceTree, storage: Storage
) -> None:
    data = pdf_bytes("merged")
    sources.add("a/file.pdf", data)
    storage.store("ATT00001", "f.pdf", data)
    lib = library(
        [
            api_item("OLD00001", deleted=True),
            api_item("NEW00001", title=TITLE, replaces=["OLD00001"]),
            pdf_attachment("ATT00001", "OLD00001", "f.pdf"),
        ]
    )
    assert _match(sources, lib, storage)["file.pdf"].item == "NEW00001"


def test_doi_match_needs_the_title_in_sequence(sources: SourceTree) -> None:
    page = f"Journal of Things. {TITLE}. doi:10.5555/abc"
    sources.add("a/x.pdf", pdf_bytes("x"), [page])
    lib = library([api_item("ITEM0001", title=TITLE, DOI="10.5555/ABC")])
    match = _match(sources, lib)["x.pdf"]
    assert (match.status, match.method, match.verdict) == (
        Status.MATCHED,
        Method.DOI,
        Verdict.CONFIRMED,
    )


def test_doi_of_a_cited_article_is_rejected_by_title(sources: SourceTree) -> None:
    page = "An unrelated essay on perception. References: Doe (1999) doi:10.5555/abc"
    sources.add("a/x.pdf", pdf_bytes("x"), [page])
    lib = library([api_item("ITEM0001", title=OTHER, DOI="10.5555/abc")])
    match = _match(sources, lib)["x.pdf"]
    assert match.status is Status.ABSENT
    assert "rejected by title" in match.note


def test_scattered_title_words_leave_the_match_to_check(sources: SourceTree) -> None:
    scattered = " ".join(reversed(TITLE.split()))
    sources.add("a/x.pdf", pdf_bytes("x"), [f"doi:10.5555/abc {scattered}"])
    lib = library([api_item("ITEM0001", title=TITLE, DOI="10.5555/abc")])
    match = _match(sources, lib)["x.pdf"]
    assert (match.status, match.verdict) == (Status.CHECK, Verdict.CHECK)
    assert match.share == 1.0


def test_scanned_pdf_is_left_to_check_not_rejected(sources: SourceTree) -> None:
    sources.add("a/2004_Smith_temporal_dynamics_attention.pdf", pdf_bytes("scan"))
    lib = library([api_item("ITEM0001", title=TITLE, date="2004", creators=["Smith"])])
    match = _match(sources, lib)["2004_Smith_temporal_dynamics_attention.pdf"]
    assert (match.status, match.method, match.verdict) == (Status.CHECK, Method.NAME, Verdict.CHECK)


def test_name_match_accepts_garbled_surnames_and_invalid_years(sources: SourceTree) -> None:
    name = "2018_Daggett_temporal_dynamics_attention_recurrent.pdf"
    sources.add(f"a/{name}", pdf_bytes("n"), [f"{TITLE}. Abstract."])
    lib = library(
        [
            api_item("ITEM0001", title=TITLE, date="0009", creators=["Daggettn Eben"]),
            api_item("ITEM0002", title=TITLE, date="1990", creators=["Daggett"]),
        ]
    )
    match = _match(sources, lib)[name]
    assert (match.status, match.item, match.method) == (Status.MATCHED, "ITEM0001", Method.NAME)


def test_reverse_search_confirms_only_a_title_that_opens_the_file(sources: SourceTree) -> None:
    filler = " ".join(["word"] * 200)
    sources.add("a/poster.pdf", pdf_bytes("p"), [f"{TITLE} poster session"])
    sources.add("a/review.pdf", pdf_bytes("r"), [f"A review. {filler} cited: {OTHER}"])
    lib = library([api_item("ITEM0001", title=TITLE), api_item("ITEM0002", title=OTHER)])
    matches = _match(sources, lib)
    assert (matches["poster.pdf"].item, matches["poster.pdf"].method) == (
        "ITEM0001",
        Method.REVERSE,
    )
    assert matches["review.pdf"].status is Status.ABSENT
    assert "cites ITEM0002" in matches["review.pdf"].note


def test_resolutions_reject_accept_assign_and_preprint(sources: SourceTree) -> None:
    sources.add("a/wrong.pdf", pdf_bytes("w"), [f"{TITLE}. Text."])
    sources.add("a/2004_Smith_temporal_dynamics.pdf", pdf_bytes("s"))
    sources.add("a/assigned.pdf", pdf_bytes("a"))
    sources.add("b/preprint.pdf", pdf_bytes("pp"))
    lib = library(
        [
            api_item("ITEM0001", title=TITLE, date="2004", creators=["Smith"]),
            api_item("ITEM0002", title=OTHER),
        ]
    )
    matches = _match(
        sources,
        lib,
        resolutions=(
            "resolutions:\n"
            "  - {file: wrong.pdf, action: reject, item: ITEM0001}\n"
            "  - {file: 2004_Smith_temporal_dynamics.pdf, action: accept, note: read page 1}\n"
            "  - {file: a/assigned.pdf, action: assign, item: ITEM0002}\n"
            "  - {file: preprint.pdf, action: preprint-of, item: ITEM0002}\n"
        ),
    )
    assert matches["wrong.pdf"].status is Status.ABSENT
    accepted = matches["2004_Smith_temporal_dynamics.pdf"]
    assert (accepted.status, accepted.item) == (Status.MATCHED, "ITEM0001")
    assert "read page 1" in accepted.note
    assigned = matches["assigned.pdf"]
    assert (assigned.status, assigned.method) == (Status.MATCHED, Method.RESOLUTION)
    assert matches["preprint.pdf"].status is Status.PREPRINT_OF


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("{file: missing.pdf, action: reject}", "names no file"),
        ("{file: a.pdf, action: assign}", "requires an `item`"),
        ("{file: a.pdf, action: delete}", "`action` must be one of"),
    ],
)
def test_invalid_resolutions_are_refused(sources: SourceTree, entry: str, message: str) -> None:
    sources.add("a/a.pdf", pdf_bytes("a"))
    path = sources.root.parent / "resolutions.yml"
    path.write_text(f"resolutions:\n  - {entry}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_resolutions(path, sources.inventory())


def test_resolution_naming_a_missing_item_fails(sources: SourceTree) -> None:
    sources.add("a/a.pdf", pdf_bytes("a"))
    with pytest.raises(ConfigError, match="not in the library"):
        _match(
            sources,
            library([]),
            resolutions="resolutions:\n  - {file: a.pdf, action: assign, item: NONE0001}\n",
        )


def test_accept_without_any_candidate_fails(sources: SourceTree) -> None:
    sources.add("a/a.pdf", pdf_bytes("a"))
    with pytest.raises(ConfigError, match="no route matches"):
        _match(
            sources, library([]), resolutions="resolutions:\n  - {file: a.pdf, action: accept}\n"
        )


def test_works_group_contents_by_doi_and_keep_the_largest_pdf(sources: SourceTree) -> None:
    sources.add("a/small.pdf", pdf_bytes("s"), ["doi:10.5555/w"])
    sources.add("a/large.pdf", pdf_bytes("a larger file"), ["doi:10.5555/w"])
    sources.add("a/alone.pdf", pdf_bytes("alone"))
    sources.add("a/notes.docx", b"not a pdf")
    works = group_works(sources.inventory())
    by_id = {work.work_id: work for work in works}
    representative = by_id["doi:10.5555/w"].representative
    assert representative is not None and representative.first.name == "large.pdf"
    docx = [w for w in works if w.members[0].first.name == "notes.docx"][0]
    assert docx.representative is None
    assert len(works) == 3


def test_inventory_reports_a_missing_folder(sources: SourceTree) -> None:
    sources.add("a/a.pdf", pdf_bytes("a"))
    with pytest.raises(ArtifactError, match="source folder not found"):
        sources.inventory(folders=["missing"])
