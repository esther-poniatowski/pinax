"""Tests of the readers of record exports, the grouping of records into works, and the inventory."""

from pathlib import Path

import pytest

from conftest import SourceTree, pdf_bytes
from pinax.errors import ArtifactError
from pinax.records.items import connector_item
from pinax.records.model import Record
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
