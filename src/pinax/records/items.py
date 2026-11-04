"""
Item data posted to the connector for a record, under the fields that Zotero holds for its type.

A field that the item type lacks would be dropped by Zotero, so it is written into `extra` as a
line `Name: value`, as a correction preserves a field. The DOI follows the same rule, since only
some types hold a DOI field.

Functions
---------
connector_item(record) -> dict[str, Any]
    Item data of a record, in the form that `saveItems` reads.
"""

from typing import Any

from pinax.records.model import Record

_COMMON = frozenset({"title", "abstractNote", "date", "language", "url", "extra", "shortTitle"})

TYPE_FIELDS: dict[str, frozenset[str]] = {
    "journalArticle": _COMMON
    | {"publicationTitle", "volume", "issue", "pages", "series", "ISSN", "DOI"},
    "conferencePaper": _COMMON
    | {"proceedingsTitle", "conferenceName", "place", "publisher", "volume", "pages"}
    | {"series", "ISBN", "DOI"},
    "preprint": _COMMON | {"repository", "archiveID", "place", "series", "DOI"},
    "bookSection": _COMMON
    | {"bookTitle", "series", "volume", "edition", "place", "publisher", "pages", "ISBN"},
    "book": _COMMON | {"series", "volume", "edition", "place", "publisher", "ISBN"},
    "thesis": _COMMON | {"thesisType", "university", "place"},
    "report": _COMMON | {"reportNumber", "institution", "place", "pages", "series"},
    "manuscript": _COMMON | {"place"},
    "webpage": _COMMON | {"websiteTitle"},
    "document": _COMMON | {"publisher"},
}
"""Fields that each item type holds; a type absent from the table holds the common fields only."""


def _creator(last: str, first: str, creator_type: str) -> dict[str, str]:
    """Creator in the form of the connector; a creator without first name is one field."""
    if first:
        return {"firstName": first, "lastName": last, "creatorType": creator_type}
    return {"name": last, "creatorType": creator_type}


def connector_item(record: Record) -> dict[str, Any]:
    """
    Item data of a record, in the form that `saveItems` reads.

    Parameters
    ----------
    record : Record
        Record holding metadata.

    Returns
    -------
    dict[str, Any]
        Item with its type, its fields valid for the type, its creators, and the other fields
        appended to `extra`.

    Examples
    --------
    >>> item = connector_item(Record("a.bib", 1, "k", "book", "Signals", doi="10.5555/b"))
    >>> item["itemType"], item["title"], item["extra"]
    ('book', 'Signals', 'DOI: 10.5555/b')
    """
    valid = TYPE_FIELDS.get(record.item_type, _COMMON)
    values = {"title": record.title, "date": record.date, **record.fields}
    if record.doi:
        values["DOI"] = record.doi
    extra = [record.fields["extra"]] if record.fields.get("extra") else []
    item: dict[str, Any] = {"itemType": record.item_type}
    for name, value in values.items():
        if not value or name == "extra":
            continue
        if name in valid:
            item[name] = value
        else:
            extra.append(f"{name}: {value}")
    if extra:
        item["extra"] = "\n".join(extra)
    item["creators"] = [
        _creator(c.last_name, c.first_name, c.creator_type) for c in record.creators
    ]
    item["tags"] = []
    item["attachments"] = []
    return item
