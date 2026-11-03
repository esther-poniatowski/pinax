"""Tests of the library snapshot, the read-only client and the storage index."""

import json
import urllib.request

import pytest

from conftest import Storage, api_collection, api_item, library, pdf_attachment, pdf_bytes
from pinax.errors import LibraryError
from pinax.hashing import digest_file
from pinax.library.client import Response, ZoteroClient, require_loopback
from pinax.library.storage import StorageIndex


def test_survivor_follows_merge_chains_and_ignores_trash() -> None:
    lib = library(
        [
            api_item("OLD00001", deleted=True),
            api_item("MID00001", deleted=True, replaces=["OLD00001"]),
            api_item("NEW00001", replaces=["MID00001"]),
            api_item("GONE0001", deleted=True),
        ]
    )
    survivor = lib.survivor("OLD00001")
    assert survivor is not None and survivor.key == "NEW00001"
    assert lib.survivor("GONE0001") is None
    assert lib.survivor("NONE0001") is None


def test_survivor_stops_on_a_cycle() -> None:
    lib = library(
        [
            api_item("AAAA0001", deleted=True, replaces=["BBBB0001"]),
            api_item("BBBB0001", deleted=True, replaces=["AAAA0001"]),
        ]
    )
    assert lib.survivor("AAAA0001") is None


def test_pdfs_dois_and_years() -> None:
    lib = library(
        [
            api_item("ITEM0001", DOI="https://doi.org/10.1/X", date="0009"),
            api_item("ITEM0002", extra="Note\nDOI: 10.1/y", date="March 2004"),
            pdf_attachment("ATT00001", "ITEM0001", "a.pdf"),
            api_item("NOTE0001", "note", parent="ITEM0001"),
        ]
    )
    assert [a.key for a in lib.pdfs("ITEM0001")] == ["ATT00001"]
    assert lib.by_doi("10.1/x") == ["ITEM0001"]
    assert lib.by_doi("10.1/Y") == ["ITEM0002"]
    assert lib.items["ITEM0001"].year is None
    assert lib.items["ITEM0002"].year == 2004


def test_collection_path_and_subtree() -> None:
    lib = library(
        [api_item("ITEM0001", collections=["LEAF0001"]), api_item("ITEM0002")],
        [
            api_collection("ROOT0001", "review"),
            api_collection("LEAF0001", "background", "ROOT0001"),
        ],
    )
    assert lib.collection_path("LEAF0001") == "review/background"
    assert lib.in_subtree(lib.items["ITEM0001"], "ROOT0001")
    assert not lib.in_subtree(lib.items["ITEM0002"], "ROOT0001")


@pytest.mark.parametrize(
    "url", ["http://192.168.1.2:23119", "https://127.0.0.1:23119", "http://zotero.org"]
)
def test_client_refuses_non_loopback_hosts(url: str) -> None:
    with pytest.raises(LibraryError, match="loopback"):
        require_loopback(url)


class FakeTransport:
    """Transport answering the local API with fixed pages, and recording the requests."""

    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Response:
        del timeout
        self.requests.append(request)
        url = request.full_url
        if "better-bibtex" in url:
            body = {"result": {"ITEM0001": "smith2004", "ITEM0002": None}}
            return Response(200, {}, json.dumps(body))
        start = int(url.rsplit("start=", 1)[1])
        page = self.items[start : start + 2]
        return Response(200, {"Total-Results": str(len(self.items))}, json.dumps(page))


def test_paged_reads_every_page_with_get_requests() -> None:
    entries = [api_item(f"ITEM000{i}") for i in range(5)]
    transport = FakeTransport(entries)
    client = ZoteroClient("http://127.0.0.1:23119", transport)
    assert [entry["key"] for entry in client.items()] == [f"ITEM000{i}" for i in range(5)]
    assert {request.get_method() for request in transport.requests} == {"GET"}
    assert all("/api/users/0/items" in r.full_url for r in transport.requests)


def test_citation_keys_drop_unknown_items() -> None:
    client = ZoteroClient("http://localhost:23119", FakeTransport([]))
    assert client.citation_keys(["ITEM0001", "ITEM0002"]) == {"ITEM0001": "smith2004"}


def test_storage_index_hashes_only_matching_sizes(storage: Storage) -> None:
    wanted = storage.store("ATT00001", "a.pdf", pdf_bytes("wanted"))
    storage.store("ATT00002", "b.pdf", pdf_bytes("a much longer and different content"))
    index = StorageIndex(storage.root)
    found = index.by_sha256([wanted.stat().st_size])
    assert found == {digest_file(wanted).sha256: "ATT00001"}
    assert StorageIndex(storage.root / "missing").by_sha256([1]) == {}
