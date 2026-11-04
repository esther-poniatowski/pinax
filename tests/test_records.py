"""Tests of the readers of record exports, the grouping of records into works, and the inventory."""

from pathlib import Path
from typing import Any

import pytest

from conftest import SourceTree, api_item, library, matching_config, pdf_bytes
from pinax.errors import ArtifactError, ConfigError
from pinax.matching.model import Method, RecordMatch, Status
from pinax.matching.resolutions import Resolutions, load_resolutions
from pinax.records.items import connector_item
from pinax.records.matching import RecordMatcher
from pinax.records.model import Record, RecordCreator
from pinax.records.readers import reader
from pinax.records.works import group_records
from pinax.sources.inventory import Inventory

BIBTEX = r"""
@article{doe2001,
  title = {A {Model} of Synthetic Signals},
  author = {Doe, Jane and van der Berg, Piet},
  journal = {Journal of Examples},
  pages = {1--10
  },
  year = {2001},
  doi = {10.5555/ONE}
}
@inproceedings{doe2001,
  title = {Another Synthetic Work},
  author = {M{\"u}ller, Ana},
  booktitle = {Proceedings of Things},
  year = 2002,
  doi = {10.5555/two}
}
@book{müller2003,
  title = {Third Synthetic Book},
  author = {Müller, Ana},
  publisher = {Example Press},
  year = {2003},
  doi = {10.5555/three}
}
"""

RIS = """TY  - JOUR
ID  - doe2001
TI  - A model of synthetic
  signals
AU  - Doe, Jane
AU  - van der Berg, Piet
JO  - Journal of Examples
SP  - 1
EP  - 10
PY  - 2001///
DO  - 10.5555/one
ER  -
"""

CSV = (
    '"Key","Item Type","Publication Year","Author","Title","Publication Title","DOI","Pages"\n'
    '"ABCD2345","journalArticle","2001","Doe, Jane; van der Berg, Piet",'
    '"A model of synthetic signals","Journal of Examples","",'
    '"1-10"\n'
    '"EFGH6789","report","1999","Some Institute","A report\nspanning lines","","",""\n'
)


def _write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_bibtex_keeps_repeated_keys_multiline_fields_and_non_ascii_keys(tmp_path: Path) -> None:
    records = reader("bibtex").read(_write(tmp_path, "refs.bib", BIBTEX), "refs.bib")
    assert [(r.position, r.key, r.doi) for r in records] == [
        (1, "doe2001", "10.5555/one"),
        (2, "doe2001", "10.5555/two"),
        (3, "müller2003", "10.5555/three"),
    ]
    first, second, third = records
    assert first.title == "A Model of Synthetic Signals"
    assert first.fields == {"publicationTitle": "Journal of Examples", "pages": "1-10"}
    assert [(c.last_name, c.first_name) for c in first.creators] == [
        ("Doe", "Jane"),
        ("van der Berg", "Piet"),
    ]
    assert second.item_type == "conferencePaper"
    assert second.creators[0].last_name == "Müller"
    assert second.fields["proceedingsTitle"] == "Proceedings of Things"
    assert (third.item_type, third.ref) == ("book", "refs.bib#3")


def test_bibtex_refuses_an_entry_that_does_not_parse(tmp_path: Path) -> None:
    text = BIBTEX + "@article{broken,\n  title = {Unclosed\n"
    with pytest.raises(ArtifactError, match="does not parse"):
        reader("bibtex").read(_write(tmp_path, "refs.bib", text), "refs.bib")


def test_ris_joins_continued_lines_and_refuses_an_open_record(tmp_path: Path) -> None:
    (record,) = reader("ris").read(_write(tmp_path, "refs.ris", RIS), "refs.ris")
    assert record.title == "A model of synthetic signals"
    assert (record.date, record.year, record.doi) == ("2001", 2001, "10.5555/one")
    assert record.fields["pages"] == "1-10"
    with pytest.raises(ArtifactError, match="not closed"):
        reader("ris").read(_write(tmp_path, "open.ris", RIS.replace("ER  -\n", "")), "open.ris")
    with pytest.raises(ArtifactError, match="outside a record"):
        reader("ris").read(_write(tmp_path, "bad.ris", "text\n" + RIS), "bad.ris")


def test_zotero_csv_reads_quoted_lines_and_refuses_another_csv(tmp_path: Path) -> None:
    records = reader("zotero-csv").read(_write(tmp_path, "refs.csv", CSV), "refs.csv")
    assert [(r.item_type, r.title, r.doi) for r in records] == [
        ("journalArticle", "A model of synthetic signals", ""),
        ("report", "A report spanning lines", ""),
    ]
    assert records[1].creators[0].last_name == "Some Institute"
    with pytest.raises(ArtifactError, match="not a CSV export of Zotero"):
        reader("zotero-csv").read(_write(tmp_path, "other.csv", "a,b\n1,2\n"), "other.csv")


def test_doi_list_refuses_a_line_without_doi(tmp_path: Path) -> None:
    text = "# reading list\n10.5555/one\n\nhttps://doi.org/10.5555/TWO\n"
    records = reader("doi-list").read(_write(tmp_path, "dois.txt", text), "dois.txt")
    assert [(r.position, r.doi, r.has_metadata) for r in records] == [
        (1, "10.5555/one", False),
        (2, "10.5555/two", False),
    ]
    with pytest.raises(ArtifactError, match="line 2 holds no DOI"):
        reader("doi-list").read(_write(tmp_path, "bad.txt", "10.5555/one\nnot a doi\n"), "x")


def test_records_of_several_exports_form_one_work_and_disagreements_are_kept(
    tmp_path: Path,
) -> None:
    bib = reader("bibtex").read(_write(tmp_path, "refs.bib", BIBTEX), "refs.bib")
    ris = reader("ris").read(_write(tmp_path, "refs.ris", RIS), "refs.ris")
    works = {work.identity: work for work in group_records(bib + ris)}
    assert len(works) == 3
    shared = works["doi:10.5555/one"]
    assert shared.refs == ("refs.bib#1", "refs.ris#1")
    assert not shared.disagreements
    title = "A model of synthetic signals"
    late = Record("late.ris", 1, "", "journalArticle", title, date="2003", doi="10.5555/one")
    disagreeing = group_records(bib + ris + [late])[0]
    assert disagreeing.disagreements == ("years differ: 2001, 2003",)


def test_title_identity_folds_case_and_keeps_the_year() -> None:
    lower = Record("a.bib", 1, "", "book", "the shape of SIGNALS", date="2001")
    upper = Record("b.csv", 1, "", "book", "The Shape of Signals", date="2001")
    assert lower.identity == upper.identity == "title:the shape signals|2001"
    assert Record("c.txt", 4, "", "", "").identity == "record:c.txt#4"


def test_connector_item_moves_fields_that_the_type_lacks_into_extra() -> None:
    record = Record(
        "a.bib",
        1,
        "k",
        "thesis",
        "A Synthetic Thesis",
        date="2004",
        doi="10.5555/t",
        fields={"university": "Example University", "volume": "3", "extra": "Note: kept"},
    )
    item = connector_item(record)
    assert item["university"] == "Example University"
    assert "volume" not in item and "DOI" not in item
    assert item["extra"] == "Note: kept\nvolume: 3\nDOI: 10.5555/t"
    article = connector_item(Record("a.bib", 2, "k", "journalArticle", "T", doi="10.5555/a"))
    assert article["DOI"] == "10.5555/a" and "extra" not in article


def test_inventory_reads_exports_as_records_not_as_files(sources: SourceTree) -> None:
    sources.add("a/paper.pdf", pdf_bytes("p"))
    sources.add("a/refs.bib", BIBTEX.encode())
    sources.add("a/notes.csv", b"not an export, kept as a file")
    inventory = sources.inventory()
    assert [f.name for f in inventory.files] == ["notes.csv", "paper.pdf"]
    assert [r.ref for r in inventory.records] == ["a/refs.bib#1", "a/refs.bib#2", "a/refs.bib#3"]
    assert {r.folder for r in inventory.records} == {"a"}
    restored = Inventory.from_json(inventory.to_json())
    assert restored.records == inventory.records


def _matches(
    records: list[Record],
    items: list[dict[str, object]],
    resolutions: str | None = None,
    directory: Path | None = None,
) -> dict[str, RecordMatch]:
    inventory = Inventory(Path("/synthetic"), [], {}, records)
    loaded = Resolutions()
    if resolutions is not None:
        assert directory is not None
        path = directory / "resolutions.yml"
        path.write_text(resolutions, encoding="utf-8")
        loaded = load_resolutions(path, inventory)
    matcher = RecordMatcher(library(items), matching_config(), loaded)
    return {match.refs[0]: match for match in matcher.match_all(group_records(records))}


def _record(position: int, title: str, **values: Any) -> Record:
    creators = tuple(RecordCreator(name) for name in values.pop("authors", ("Doe",)))
    return Record(
        "refs.bib",
        position,
        values.pop("key", "doe2001"),
        "journalArticle",
        title,
        creators,
        **values
    )


def test_records_match_by_doi_confirmed_by_title_and_by_title_without_doi() -> None:
    records = [
        _record(1, "A Model of Synthetic Signals", date="2001", doi="10.5555/one"),
        _record(2, "Another Synthetic Work", date="2002", doi="10.5555/two"),
        _record(3, "THE CASE OF A SYNTHETIC TITLE", date="2003"),
        _record(4, "A Synthetic Title Twice", date="2004"),
        _record(5, "A Synthetic Work Out of Range", date="1990"),
        _record(6, "Nothing Like It", date="2006"),
    ]
    items = [
        api_item(
            "ITEM0001",
            title="A model of synthetic signals",
            DOI="10.5555/one",
            date="2001",
            creators=["Doe"],
        ),
        api_item("ITEM0002", title="A different title", DOI="10.5555/two", creators=["Doe"]),
        api_item("ITEM0003", title="The case of a synthetic title", date="2003", creators=["Doe"]),
        api_item("ITEM0004", title="A synthetic title twice", date="2004", creators=["Doe"]),
        api_item("ITEM0005", title="A synthetic title twice", date="2004", creators=["Doe"]),
        api_item("ITEM0006", title="A synthetic work out of range", date="2010", creators=["Doe"]),
    ]
    found = _matches(records, items)
    outcome = {ref: (m.status, m.item, m.method) for ref, m in found.items()}
    assert outcome["refs.bib#1"] == (Status.MATCHED, "ITEM0001", Method.DOI)
    assert outcome["refs.bib#2"] == (Status.CHECK, "ITEM0002", Method.DOI)
    assert outcome["refs.bib#3"] == (Status.MATCHED, "ITEM0003", Method.TITLE)
    assert outcome["refs.bib#4"][0] is Status.CHECK
    assert outcome["refs.bib#5"] == (Status.CHECK, "ITEM0006", Method.TITLE)
    assert outcome["refs.bib#6"] == (Status.ABSENT, "", None)
    assert "another title" in found["refs.bib#2"].note


def test_repeated_keys_match_two_items() -> None:
    records = [
        _record(1, "A Synthetic Preprint", date="2001", doi="10.5555/pre"),
        _record(2, "A Synthetic Abstract", date="2001", doi="10.5555/abs"),
    ]
    items = [
        api_item("ITEMPRE1", title="A synthetic preprint", DOI="10.5555/pre"),
        api_item("ITEMABS1", title="A synthetic abstract", DOI="10.5555/abs"),
    ]
    found = _matches(records, items)
    assert [found[ref].item for ref in ("refs.bib#1", "refs.bib#2")] == ["ITEMPRE1", "ITEMABS1"]


def test_disagreeing_records_wait_for_a_resolution(tmp_path: Path) -> None:
    records = [
        _record(1, "A Synthetic Work", date="2001", doi="10.5555/w"),
        Record(
            "refs.ris", 1, "", "journalArticle", "A Synthetic Work", date="2004", doi="10.5555/w"
        ),
    ]
    found = _matches(records, [])
    assert found["refs.bib#1"].status is Status.CHECK
    assert "years differ: 2001, 2004" in found["refs.bib#1"].note
    resolved = _matches(
        records, [], "resolutions:\n  - {record: doi:10.5555/W, action: reject}\n", tmp_path
    )
    assert resolved["refs.bib#1"].status is Status.ABSENT


def test_record_resolutions_name_a_record_or_a_work(tmp_path: Path) -> None:
    records = [_record(1, "A Synthetic Work", date="2001"), _record(2, "Other", date="2002")]
    items = [api_item("ITEM0001", title="Unrelated"), api_item("ITEM0002", title="Other")]
    text = (
        "resolutions:\n"
        "  - {record: 'refs.bib#1', action: assign, item: ITEM0001}\n"
        "  - {record: 'title:other|2002', action: reject, item: ITEM0002}\n"
    )
    found = _matches(records, items, text, tmp_path)
    assert (found["refs.bib#1"].status, found["refs.bib#1"].method) == (
        Status.MATCHED,
        Method.RESOLUTION,
    )
    assert found["refs.bib#2"].status is Status.ABSENT
    with pytest.raises(ConfigError, match="names no record"):
        _matches(
            records, items, "resolutions:\n  - {record: 'refs.bib#9', action: accept}\n", tmp_path
        )
    with pytest.raises(ConfigError, match="exactly one `file` or `record`"):
        _matches(
            records, items, "resolutions:\n  - {file: a.pdf, record: x, action: accept}\n", tmp_path
        )
