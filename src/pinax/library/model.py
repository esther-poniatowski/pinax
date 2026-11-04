"""
Typed snapshot of a Zotero library, built from the JSON of the local API.

Classes
-------
Collection
    One collection and its parent.
Item
    One item of any type: a regular item, an attachment or a note.
Library
    Items and collections of one snapshot, with the lookups that matching and checks need.

Notes
-----
A merge in Zotero deletes the absorbed items, and the surviving item lists them in
`relations["dc:replaces"]`. `Library.survivor` follows that chain, so an item key recorded before a
merge still resolves to the item that holds its content.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from pinax.text import normalize_doi, words

NON_REGULAR_TYPES = frozenset({"attachment", "note", "annotation"})
"""Item types that are not references: they hang under a regular item or stand alone."""

PDF_TYPE = "application/pdf"

VENUE_FIELDS = (
    "publicationTitle",
    "bookTitle",
    "proceedingsTitle",
    "publisher",
    "university",
    "websiteTitle",
    "encyclopediaTitle",
    "institution",
)
"""Fields that name where a work appeared; an item with none of them lacks its venue."""

_YEAR = re.compile(r"\b(1[5-9]|20)\d\d\b")
_DOI_IN_EXTRA = re.compile(r"^\s*DOI:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Collection:
    """
    One collection and its parent.

    Attributes
    ----------
    key : str
        Collection key.
    name : str
        Display name.
    parent : str | None
        Key of the parent collection, None at the top level.
    """

    key: str
    name: str
    parent: str | None


@dataclass(frozen=True)
class Item:  # pylint: disable=too-many-instance-attributes
    """
    One item of any type: a regular item, an attachment or a note.

    Attributes
    ----------
    key : str
        Item key.
    item_type : str
        Zotero item type, such as `journalArticle` or `attachment`.
    fields : Mapping[str, str]
        String fields of the item (`title`, `date`, `DOI`, `extra`, `filename`, `md5`...).
    surnames : tuple[str, ...]
        Last names of the creators, or the single name of a creator recorded in one field.
    collections : tuple[str, ...]
        Keys of the collections that hold the item directly.
    parent : str | None
        Key of the parent item of an attachment or a note.
    deleted : bool
        Whether the item lies in the trash.
    replaces : tuple[str, ...]
        Keys of the items absorbed into this one by merges.
    """

    key: str
    item_type: str
    fields: Mapping[str, str] = field(default_factory=dict)
    surnames: tuple[str, ...] = ()
    collections: tuple[str, ...] = ()
    parent: str | None = None
    deleted: bool = False
    replaces: tuple[str, ...] = ()

    def get(self, name: str) -> str:
        """Value of a string field, empty when absent."""
        return self.fields.get(name, "")

    @property
    def title(self) -> str:
        """Title of the item."""
        return self.get("title")

    @property
    def citation_key(self) -> str:
        """Citation key recorded in the item."""
        return self.get("citationKey")

    @property
    def is_regular(self) -> bool:
        """Whether the item is a reference rather than an attachment, a note or an annotation."""
        return self.item_type not in NON_REGULAR_TYPES

    @property
    def is_pdf(self) -> bool:
        """Whether the item is a PDF attachment."""
        return self.item_type == "attachment" and self.get("contentType") == PDF_TYPE

    @property
    def year(self) -> int | None:
        """Year of the `date` field, None when the field holds no plausible year."""
        found = _YEAR.search(self.get("date"))
        return int(found.group(0)) if found else None

    @property
    def dois(self) -> tuple[str, ...]:
        """Normalized DOIs of the `DOI` field and of `DOI:` lines in `extra`."""
        found = [normalize_doi(self.get("DOI"))] if self.get("DOI") else []
        found += [normalize_doi(m) for m in _DOI_IN_EXTRA.findall(self.get("extra"))]
        return tuple(dict.fromkeys(doi for doi in found if doi))

    @property
    def venue(self) -> str:
        """First non-empty field of `VENUE_FIELDS`."""
        return next((self.get(name) for name in VENUE_FIELDS if self.get(name)), "")

    def holds_work(self, doi: str, title: str) -> bool:
        """
        Whether the item is a live regular item holding a work, by its DOI or else by its title.

        Parameters
        ----------
        doi : str
            DOI of the work, empty when the work has none.
        title : str
            Title of the work, compared after folding case and accents when the work has no DOI.

        Returns
        -------
        bool
            True when the item records the DOI, or, without a DOI, carries the same title.
        """
        if self.deleted or not self.is_regular:
            return False
        if doi:
            return normalize_doi(doi) in self.dois
        return " ".join(words(self.title)) == " ".join(words(title))

    @classmethod
    def from_api(cls, entry: Mapping[str, Any]) -> "Item":
        """
        Build an item from one entry of the local API.

        Parameters
        ----------
        entry : Mapping[str, Any]
            Entry with a `data` mapping, as returned by `/api/users/0/items`.

        Returns
        -------
        Item
            Typed item.
        """
        data: Mapping[str, Any] = entry.get("data", entry)
        fields = {k: v for k, v in data.items() if isinstance(v, str)}
        surnames = tuple(
            str(creator.get("lastName") or creator.get("name") or "")
            for creator in data.get("creators", [])
            if isinstance(creator, Mapping)
        )
        relations = data.get("relations", {})
        replaced = relations.get("dc:replaces", []) if isinstance(relations, Mapping) else []
        uris = [replaced] if isinstance(replaced, str) else list(replaced)
        return cls(
            key=str(data["key"]),
            item_type=str(data["itemType"]),
            fields=fields,
            surnames=tuple(name for name in surnames if name),
            collections=tuple(data.get("collections", [])),
            parent=data.get("parentItem") or None,
            deleted=bool(data.get("deleted")),
            replaces=tuple(str(uri).rsplit("/", 1)[-1] for uri in uris),
        )


class Library:
    """
    Items and collections of one snapshot, with the lookups that matching and checks need.

    Parameters
    ----------
    items : Iterable[Item]
        Every item of the snapshot, trashed items included.
    collections : Iterable[Collection]
        Every collection of the snapshot.

    Attributes
    ----------
    items : dict[str, Item]
        Items by key.
    collections : dict[str, Collection]
        Collections by key.
    """

    def __init__(self, items: Iterable[Item], collections: Iterable[Collection]) -> None:
        self.items = {item.key: item for item in items}
        self.collections = {collection.key: collection for collection in collections}
        self._replaced_by: dict[str, str] = {}
        self._attachments: dict[str, list[Item]] = {}
        self._by_doi: dict[str, list[str]] = {}
        # A trashed item absorbed by a later merge still records what it absorbed before, so the
        # merge map reads every item; reading live items only would break such chains.
        for item in self.items.values():
            for absorbed in item.replaces:
                self._replaced_by[absorbed] = item.key
        for item in self.live():
            if item.item_type == "attachment" and item.parent:
                self._attachments.setdefault(item.parent, []).append(item)
            if item.is_regular:
                for doi in item.dois:
                    self._by_doi.setdefault(doi, []).append(item.key)

    @classmethod
    def from_api(
        cls, items: Iterable[Mapping[str, Any]], collections: Iterable[Mapping[str, Any]]
    ) -> "Library":
        """
        Build a library from the JSON lists of the local API.

        Parameters
        ----------
        items : Iterable[Mapping[str, Any]]
            Entries of `/api/users/0/items`.
        collections : Iterable[Mapping[str, Any]]
            Entries of `/api/users/0/collections`.

        Returns
        -------
        Library
            Typed snapshot.
        """
        typed_collections = []
        for entry in collections:
            data = entry.get("data", entry)
            typed_collections.append(
                Collection(
                    key=str(data["key"]),
                    name=str(data.get("name", "")),
                    parent=data.get("parentCollection") or None,
                )
            )
        return cls((Item.from_api(entry) for entry in items), typed_collections)

    def live(self) -> Iterator[Item]:
        """Items outside the trash."""
        return (item for item in self.items.values() if not item.deleted)

    def regular(self) -> Iterator[Item]:
        """Live regular items, the references of the library."""
        return (item for item in self.live() if item.is_regular)

    def get_live(self, key: str) -> Item | None:
        """Item of a key when it exists outside the trash."""
        item = self.items.get(key)
        return item if item is not None and not item.deleted else None

    def survivor(self, key: str) -> Item | None:
        """
        Live item that holds the content of a key, following merges.

        Parameters
        ----------
        key : str
            Item key, possibly of an item absorbed by a merge.

        Returns
        -------
        Item | None
            The item itself when live, otherwise the end of its `dc:replaces` chain, or None when
            the chain ends on a missing or trashed item.
        """
        seen: set[str] = set()
        while key not in seen:
            seen.add(key)
            item = self.get_live(key)
            if item is not None:
                return item
            if key not in self._replaced_by:
                return None
            key = self._replaced_by[key]
        return None

    def attachments(self, key: str) -> list[Item]:
        """Live attachments of a regular item."""
        return list(self._attachments.get(key, []))

    def pdfs(self, key: str) -> list[Item]:
        """Live PDF attachments of a regular item."""
        return [item for item in self.attachments(key) if item.is_pdf]

    def by_doi(self, doi: str) -> list[str]:
        """Keys of the live regular items that record a DOI."""
        return list(dict.fromkeys(self._by_doi.get(normalize_doi(doi), [])))

    def collection_path(self, key: str) -> str:
        """
        Path of a collection from the top level, names joined by `/`.

        Parameters
        ----------
        key : str
            Collection key.

        Returns
        -------
        str
            Full path, or the key itself when the collection is unknown.
        """
        names: list[str] = []
        current: str | None = key
        while current is not None and current in self.collections and len(names) < 64:
            names.append(self.collections[current].name)
            current = self.collections[current].parent
        return "/".join(reversed(names)) if names else key

    def in_subtree(self, item: Item, root: str) -> bool:
        """
        Whether an item lies in a collection or in one of its descendants.

        Parameters
        ----------
        item : Item
            Item to test.
        root : str
            Key of the collection at the root of the sub-tree.

        Returns
        -------
        bool
            True when one of the collections of the item descends from `root`.
        """
        for key in item.collections:
            current: str | None = key
            depth = 0
            while current is not None and depth < 64:
                if current == root:
                    return True
                collection = self.collections.get(current)
                current = collection.parent if collection else None
                depth += 1
        return False
