"""
Reference list of each source folder: the citation keys of the items holding its files and the
records of its exports.

Functions
---------
render_references(rows, header) -> str
    Render the citation keys of each folder and the unresolved files as YAML.
shared_keys(rows) -> dict[str, list[str]]
    Citation keys carried by several items.
"""

from collections.abc import Sequence

import yaml

from pinax.exports.evidence import EvidenceRow, RecordRow, Route

DEFAULT_HEADER = (
    "# Citation keys of the items that hold the files and records of each source folder, written\n"
    "# by pinax.\n"
    "# Fields:\n"
    "#   folders     one sorted list of citation keys per folder\n"
    "#   unresolved  the files and records that no item with a citation key holds\n"
)


def render_references(rows: Sequence[EvidenceRow | RecordRow], header: str = DEFAULT_HEADER) -> str:
    """
    Render the citation keys of each folder and the unresolved sources as YAML.

    Parameters
    ----------
    rows : Sequence[EvidenceRow | RecordRow]
        Evidence rows of the files and of the records.
    header : str
        Comment block written before the data; the consumer supplies its own provenance.

    Returns
    -------
    str
        YAML document with `folders` and `unresolved`.
    """
    folders: dict[str, set[str]] = {}
    unresolved: list[str] = []
    for row in rows:
        if row.route is Route.UNRESOLVED:
            unresolved.append(row.label)
        else:
            folders.setdefault(row.folder, set()).add(row.citation_key)
    data = {
        "folders": {folder: sorted(keys) for folder, keys in sorted(folders.items())},
        "unresolved": sorted(unresolved),
    }
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return (header.rstrip("\n") + "\n" if header else "") + body


def shared_keys(rows: Sequence[EvidenceRow | RecordRow]) -> dict[str, list[str]]:
    """
    Citation keys carried by several items.

    Parameters
    ----------
    rows : Sequence[EvidenceRow | RecordRow]
        Evidence rows of the files and of the records.

    Returns
    -------
    dict[str, list[str]]
        Item keys of each citation key held by more than one item; the library can hold one key
        twice, and a reference list then cites an ambiguous key.
    """
    items: dict[str, set[str]] = {}
    for row in rows:
        if row.citation_key:
            items.setdefault(row.citation_key, set()).add(row.item)
    return {key: sorted(keys) for key, keys in items.items() if len(keys) > 1}
