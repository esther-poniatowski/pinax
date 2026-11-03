"""
Corrections of item records, read from a YAML file.

Metadata retrieval misreads some files, for example taking a cover-page line for the title or
recording a proceedings volume as a book. The researcher records each correction once:

.. code-block:: yaml

    corrections:
      - item: ABCD2345
        type: thesis                        # optional new item type
        fields: {date: "2012-03-08", university: "Some University"}
        creators:                           # optional, replaces the creators
          - {lastName: Doe, firstName: Jane, creatorType: author}
        carry: {publicationTitle: bookTitle}  # optional, read before the type change
        preserve: [DOI]                     # optional, kept or moved into `extra`
        note: the drop recorded the thesis as a journal article

Functions
---------
load_corrections(path) -> tuple[CorrectOp, ...]
    Read a corrections file.
"""

from pathlib import Path
from typing import Any

import yaml

from pinax.errors import ConfigError
from pinax.plans.model import CorrectOp, CreatorSpec

_KNOWN = {"item", "type", "fields", "creators", "carry", "preserve", "note"}


def _strings(value: Any, where: str) -> dict[str, str]:
    """Mapping of strings of an entry, empty when absent."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping of strings")
    return {str(k): str(v) for k, v in value.items()}


def _creators(value: Any, where: str) -> tuple[CreatorSpec, ...] | None:
    """Creators of an entry, None when the entry keeps the current creators."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ConfigError(f"{where}: `creators` must be a list")
    creators = []
    for creator in value:
        if not isinstance(creator, dict) or not creator.get("lastName"):
            raise ConfigError(f"{where}: each creator needs a `lastName`")
        creators.append(
            CreatorSpec(
                last_name=str(creator["lastName"]),
                first_name=str(creator.get("firstName", "")),
                creator_type=str(creator.get("creatorType", "author")),
            )
        )
    return tuple(creators)


def load_corrections(path: Path | None) -> tuple[CorrectOp, ...]:
    """
    Read a corrections file.

    Parameters
    ----------
    path : Path | None
        Corrections file; None yields no correction.

    Returns
    -------
    tuple[CorrectOp, ...]
        Corrections in file order.

    Raises
    ------
    ConfigError
        If an entry is malformed, holds an unknown key, or corrects one item twice.
    """
    if path is None:
        return ()
    if not path.is_file():
        raise ConfigError(f"corrections file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or set(data) - {"corrections"}:
        raise ConfigError(f"{path} must hold only the key `corrections`")
    entries = data.get("corrections", [])
    if not isinstance(entries, list):
        raise ConfigError(f"{path} must hold a list under `corrections`")
    corrections: list[CorrectOp] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{path}: correction {index + 1}"
        if not isinstance(entry, dict) or not isinstance(entry.get("item"), str):
            raise ConfigError(f"{where} must name an `item`")
        unknown = sorted(set(entry) - _KNOWN)
        if unknown:
            raise ConfigError(f"{where}: unknown keys {", ".join(unknown)}")
        if entry["item"] in seen:
            raise ConfigError(f"{where}: item {entry["item"]} is corrected twice")
        seen.add(entry["item"])
        preserve = entry.get("preserve", [])
        if not isinstance(preserve, list):
            raise ConfigError(f"{where}: `preserve` must be a list")
        corrections.append(
            CorrectOp(
                item=entry["item"],
                item_type=str(entry.get("type", "")),
                fields=_strings(entry.get("fields"), f"{where}: `fields`"),
                creators=_creators(entry.get("creators"), where),
                carry=_strings(entry.get("carry"), f"{where}: `carry`"),
                preserve=tuple(str(name) for name in preserve),
                note=str(entry.get("note", "")),
            )
        )
    return tuple(corrections)
