"""
Pytest configuration and shared fixtures for pinax tests.

Every fixture is synthetic: invented item keys, titles and paths under the temporary directory of
each test. No test reads a real Zotero library or a real folder of references.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any

import pytest

from pinax.config import MatchingConfig, SourcesConfig, load_defaults
from pinax.library.model import Library
from pinax.names import NameTemplate, compile_template
from pinax.sources.inventory import Inventory, build_inventory


def api_item(  # pylint: disable=too-many-arguments
    key: str,
    item_type: str = "journalArticle",
    *,
    title: str = "",
    date: str = "",
    creators: Sequence[str] = (),
    collections: Sequence[str] = (),
    parent: str | None = None,
    deleted: bool = False,
    replaces: Sequence[str] = (),
    **fields: str,
) -> dict[str, Any]:
    """
    Entry of the local API for one item.

    Parameters
    ----------
    key : str
        Item key.
    item_type : str
        Zotero item type.
    title, date : str
        Fields of a regular item.
    creators : Sequence[str]
        Last names of the authors.
    collections : Sequence[str]
        Collection keys.
    parent : str | None
        Parent key of an attachment.
    deleted : bool
        Whether the item is in the trash.
    replaces : Sequence[str]
        Keys absorbed by merges.
    **fields : str
        Other string fields, such as `DOI`, `extra`, `md5`, `filename`, `contentType`.

    Returns
    -------
    dict[str, Any]
        Entry with a `data` mapping.
    """
    data: dict[str, Any] = {"key": key, "itemType": item_type, **fields}
    if title:
        data["title"] = title
    if date:
        data["date"] = date
    if creators:
        data["creators"] = [{"lastName": name, "creatorType": "author"} for name in creators]
    if collections:
        data["collections"] = list(collections)
    if parent:
        data["parentItem"] = parent
    if deleted:
        data["deleted"] = 1
    if replaces:
        data["relations"] = {
            "dc:replaces": [f"http://zotero.org/users/local/abc/items/{k}" for k in replaces]
        }
    return {"key": key, "data": data}


def pdf_attachment(key: str, parent: str | None, filename: str, **fields: str) -> dict[str, Any]:
    """Entry of a PDF attachment."""
    return api_item(
        key, "attachment", parent=parent, filename=filename, contentType="application/pdf", **fields
    )


def api_collection(key: str, name: str, parent: str | None = None) -> dict[str, Any]:
    """Entry of the local API for one collection."""
    data: dict[str, Any] = {"key": key, "name": name, "parentCollection": parent or False}
    return {"key": key, "data": data}


def matching_config(**overrides: Any) -> MatchingConfig:
    """Matching section of the shipped defaults, with some keys overridden."""
    return MatchingConfig.from_mapping({**load_defaults()["matching"], **overrides})


def name_templates(*texts: str) -> tuple[NameTemplate, ...]:
    """Compiled templates, by default those of the shipped defaults."""
    return tuple(compile_template(text) for text in texts or load_defaults()["sources"]["names"])


def sources_config(root: Path, folders: Sequence[str] = ()) -> SourcesConfig:
    """Sources section of the shipped defaults for a root and its folders."""
    defaults = load_defaults()["sources"]
    return SourcesConfig(
        root=root,
        folders=tuple(folders),
        ignore=tuple(defaults["ignore"]),
        pages=defaults["pages"],
        names=name_templates(),
    )


def pdf_bytes(marker: str) -> bytes:
    """Bytes of a fake PDF, distinct for each marker."""
    return f"%PDF-1.4 {marker}\n".encode()


def md5_of(data: bytes) -> str:
    """MD5 of bytes."""
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


@dataclass
class FakeReader:
    """
    PDF reader serving texts by file content, for tests.

    Attributes
    ----------
    texts : dict[bytes, list[str]]
        Pages of each file, keyed by its bytes.
    titles : dict[bytes, str]
        Metadata title of each file.
    """

    texts: dict[bytes, list[str]] = field(default_factory=dict)
    titles: dict[bytes, str] = field(default_factory=dict)

    def pages(self, path: Path, count: int) -> list[str]:
        """Pages registered for the bytes of the file."""
        return self.texts.get(path.read_bytes(), [])[:count]

    def title(self, path: Path) -> str:
        """Title registered for the bytes of the file."""
        return self.titles.get(path.read_bytes(), "")


@dataclass
class SourceTree:
    """
    Folder of synthetic reference files and the reader of their texts.

    Attributes
    ----------
    root : Path
        Root of the sources.
    reader : FakeReader
        Texts and titles of the files.
    """

    root: Path
    reader: FakeReader = field(default_factory=FakeReader)

    def add(self, relative: str, data: bytes, pages: Sequence[str] = (), title: str = "") -> Path:
        """Write a file and register its pages."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if pages:
            self.reader.texts[data] = list(pages)
        if title:
            self.reader.titles[data] = title
        return path

    def inventory(self, folders: Sequence[str] = ()) -> Inventory:
        """Inventory of the tree."""
        return build_inventory(sources_config(self.root, folders), self.reader)


@pytest.fixture(name="sources")
def fixture_sources(tmp_path: Path) -> SourceTree:
    """Empty source tree under the temporary directory."""
    return SourceTree(tmp_path / "sources")


@dataclass
class Storage:
    """
    Zotero-style storage directory: one sub-directory per attachment key.

    Attributes
    ----------
    root : Path
        Storage directory.
    """

    root: Path

    def store(self, attachment: str, filename: str, data: bytes) -> Path:
        """Write bytes as the stored file of an attachment."""
        path = self.root / attachment / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


@pytest.fixture(name="storage")
def fixture_storage(tmp_path: Path) -> Storage:
    """Empty storage directory under the temporary directory."""
    return Storage(tmp_path / "storage")


def library(items: Sequence[dict[str, Any]], collections: Sequence[dict[str, Any]] = ()) -> Library:
    """Library built from API entries."""
    return Library.from_api(items, collections)
