"""Tests of the creation of items through the connector, against a fake of the application."""

import pytest

from conftest import api_collection, api_item, library
from fake_zotero import FakeZotero
from pinax.errors import LibraryError
from pinax.library.client import ZoteroClient
from pinax.library.connector import Connector, CreationRun, Outcome, numeric_targets
from pinax.library.model import Library
from pinax.plans.model import CreateOp
from pinax.records.items import connector_item
from pinax.records.model import Record, RecordCreator

URL = "http://127.0.0.1:23119"


def _op(position: int, title: str, doi: str = "") -> CreateOp:
    record = Record(
        "refs.bib",
        position,
        "",
        "journalArticle",
        title,
        (RecordCreator("Doe", "Jane"),),
        "2001",
        doi,
    )
    return CreateOp(record.identity, title, doi, connector_item(record), "BACKGR01", (record.ref,))


def _snapshot(zotero: FakeZotero) -> Library:
    return library([], zotero.collections())


def _run(zotero: FakeZotero) -> CreationRun:
    targets = numeric_targets(zotero.targets(), _snapshot(zotero))
    client = ZoteroClient(URL, zotero.transport)
    return CreationRun(client, Connector(URL, zotero.transport), targets, sleep=lambda _: None)


OPS = [
    _op(1, "A Model of Synthetic Signals", "10.5555/one"),
    _op(2, "Another Synthetic Work"),
]


def test_targets_follow_the_levels_and_must_match_the_snapshot() -> None:
    zotero = FakeZotero()
    assert numeric_targets(zotero.targets(), _snapshot(zotero)) == {
        "REVIEW01": "C1",
        "BACKGR01": "C2",
        "ELSEWH01": "C3",
    }
    larger = library([], [*zotero.collections(), api_collection("EXTRA001", "new")])
    with pytest.raises(LibraryError, match="differ from the snapshot"):
        numeric_targets(zotero.targets(), larger)
    with pytest.raises(LibraryError, match="unexpected connector target"):
        numeric_targets({"targets": [{"id": "X1", "name": "a", "level": 0}]}, larger)


def test_items_are_created_retargeted_and_verified() -> None:
    zotero = FakeZotero()
    logs: list[int] = []
    results = _run(zotero).run(OPS, record=lambda done: logs.append(len(done)))
    assert [(r.outcome, r.item) for r in results] == [
        (Outcome.CREATED, "NEW00001"),
        (Outcome.CREATED, "NEW00002"),
    ]
    assert logs == [1, 2]
    assert all(e["data"]["collections"] == ["BACKGR01"] for e in zotero.items)
    assert zotero.posts == ["saveItems", "updateSession"] * 2


def test_an_existing_identity_is_skipped_without_writing() -> None:
    zotero = FakeZotero(
        items=[api_item("OLD00001", title="A model of synthetic signals", DOI="10.5555/ONE")]
    )
    results = _run(zotero).run(OPS[:1])
    assert [(r.outcome, r.item) for r in results] == [(Outcome.EXISTS, "OLD00001")]
    assert not zotero.posts


def test_an_item_left_outside_its_destination_stops_the_run() -> None:
    zotero = FakeZotero(ignore_update=True)
    results = _run(zotero).run(OPS)
    assert [r.outcome for r in results] == [Outcome.FAILED]
    assert "not in the destination BACKGR01" in results[0].detail
    assert len(zotero.items) == 1


def test_an_ambiguous_write_stops_the_run_and_a_second_run_finds_the_item() -> None:
    zotero = FakeZotero(fail_save=True)
    results = _run(zotero).run(OPS)
    assert [r.outcome for r in results] == [Outcome.AMBIGUOUS]
    zotero.fail_save = False
    assert [r.outcome for r in _run(zotero).run(OPS, limit=1)] == [Outcome.CREATED]
    assert [r.outcome for r in _run(zotero).run(OPS)] == [Outcome.EXISTS, Outcome.CREATED]


def test_a_duplicate_after_the_write_fails() -> None:
    zotero = FakeZotero(duplicate=True)
    results = _run(zotero).run(OPS)
    assert [r.outcome for r in results] == [Outcome.FAILED]
    assert "NEW00001, NEW00002" in results[0].detail
