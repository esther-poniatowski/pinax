"""
Manual resolutions of matches, read from a YAML file.

A resolution records a decision taken by reading a file or a record, for a content or a record work
that the automatic routes match wrongly or cannot confirm. The file holds a list under
`resolutions`, each entry naming either a `file` or a `record`:

.. code-block:: yaml

    resolutions:
      - file: 2004_smith_model.pdf   # file name, path relative to the sources, or `sha256:`
        action: reject               # reject | accept | assign | preprint-of
        item: ABCD2345               # required by assign and preprint-of
        note: the DOI on page 1 is the DOI of a cited article
      - record: refs/export.bib#3    # export file and position, or an identity such as `doi:`
        action: assign
        item: EFGH6789

Classes
-------
Action
    Decision of a resolution.
Resolution
    Decision on one content.
Resolutions
    Resolutions by SHA-256 of the content, or by identity of the record work, they concern.

Functions
---------
load_resolutions(path, inventory) -> Resolutions
    Read a resolutions file and attach each entry to one content.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re

import yaml

from pinax.errors import ConfigError
from pinax.records.model import Record
from pinax.sources.inventory import Content, Inventory
from pinax.text import normalize_doi

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KNOWN = {"file", "record", "action", "item", "note"}


class Action(StrEnum):
    """
    Decision of a resolution.

    `REJECT` drops the candidate item (or the given item); `ACCEPT` confirms a candidate left to
    check; `ASSIGN` matches the content to the given item; `PREPRINT_OF` records that the given
    item holds another version of the work.
    """

    REJECT = "reject"
    ACCEPT = "accept"
    ASSIGN = "assign"
    PREPRINT_OF = "preprint-of"


@dataclass(frozen=True)
class Resolution:
    """
    Decision on one content.

    Attributes
    ----------
    action : Action
        Decision.
    item : str
        Item key; empty for an `accept`, or for a `reject` of whatever candidate is proposed.
    note : str
        Reason, copied into the match.
    """

    action: Action
    item: str = ""
    note: str = ""


class Resolutions:
    """
    Resolutions by SHA-256 of the content, or by identity of the record work, they concern.

    Parameters
    ----------
    entries : dict[str, Resolution]
        Resolution of each content.
    records : dict[str, Resolution]
        Resolution of each record work, by identity.
    """

    def __init__(
        self,
        entries: dict[str, Resolution] | None = None,
        records: dict[str, Resolution] | None = None,
    ) -> None:
        self._entries = dict(entries or {})
        self._records = dict(records or {})

    def get(self, sha256: str) -> Resolution | None:
        """Resolution of a content, if any."""
        return self._entries.get(sha256)

    def record(self, identity: str) -> Resolution | None:
        """Resolution of a record work, if any."""
        return self._records.get(identity)

    def __len__(self) -> int:
        return len(self._entries) + len(self._records)


def _resolve_target(reference: str, contents: Iterable[Content]) -> str:
    """SHA-256 named by a reference: a `sha256:` prefix, or the name or path of one content."""
    if reference.startswith("sha256:"):
        return reference.removeprefix("sha256:")
    found = {
        content.sha256
        for content in contents
        for file in content.files
        if reference in (file.name, str(file.relative))
    }
    if len(found) != 1:
        state = "no file" if not found else f"{len(found)} distinct contents"
        raise ConfigError(f"resolution target `{reference}` names {state}; use its relative path")
    return found.pop()


def _resolve_record(reference: str, records: Iterable[Record]) -> str:
    """Identity named by a reference: the reference of one record, or an identity of a work."""
    records = list(records)
    if reference.startswith("doi:"):
        reference = f"doi:{normalize_doi(reference.removeprefix("doi:"))}"
    identities = {record.identity for record in records}
    if reference in identities:
        return reference
    found = {record.identity for record in records if record.ref == reference}
    if not found:
        raise ConfigError(f"resolution target `{reference}` names no record or work of records")
    return found.pop()


def _resolution(entry: dict[str, object], where: str) -> Resolution:
    """Decision of an entry: its action, its item, which `assign` and `preprint-of` require, and
    its note."""
    try:
        action = Action(str(entry.get("action")))
    except ValueError as error:
        choices = ", ".join(a.value for a in Action)
        raise ConfigError(f"{where}: `action` must be one of {choices}") from error
    item = str(entry.get("item") or "")
    if action in (Action.ASSIGN, Action.PREPRINT_OF) and not item:
        raise ConfigError(f"{where}: `{action.value}` requires an `item`")
    return Resolution(action, item, str(entry.get("note") or ""))


def load_resolutions(path: Path | None, inventory: Inventory) -> Resolutions:
    """
    Read a resolutions file and attach each entry to one content.

    Parameters
    ----------
    path : Path | None
        Resolutions file; None yields no resolution.
    inventory : Inventory
        Inventory whose contents the entries name.

    Returns
    -------
    Resolutions
        Resolutions by content.

    Raises
    ------
    ConfigError
        If the file or an entry holds an unknown key, an entry is malformed, names no unique
        content or record work or lacks a required item, or two entries concern the same content
        or work.
    """
    if path is None:
        return Resolutions()
    if not path.is_file():
        raise ConfigError(f"resolutions file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or set(data) - {"resolutions"}:
        raise ConfigError(f"{path} must hold only the key `resolutions`")
    entries = data.get("resolutions", [])
    if not isinstance(entries, list):
        raise ConfigError(f"{path} must hold a list under `resolutions`")
    resolved: dict[str, Resolution] = {}
    by_record: dict[str, Resolution] = {}
    for index, entry in enumerate(entries):
        where = f"{path}: resolution {index + 1}"
        named = [key for key in ("file", "record") if isinstance(entry, dict) and key in entry]
        if len(named) != 1 or not isinstance(entry[named[0]], str):
            raise ConfigError(f"{where} must name exactly one `file` or `record`")
        unknown = sorted(set(entry) - _KNOWN)
        if unknown:
            raise ConfigError(f"{where}: unknown keys {", ".join(unknown)}")
        resolution = _resolution(entry, where)
        if named[0] == "record":
            identity = _resolve_record(entry["record"], inventory.records)
            if identity in by_record:
                raise ConfigError(f"{where}: a second resolution for the work {identity}")
            by_record[identity] = resolution
            continue
        sha = _resolve_target(entry["file"], inventory)
        if not _SHA256.match(sha) or sha not in inventory.contents:
            raise ConfigError(f"{where}: no content {sha} in the inventory")
        if sha in resolved:
            raise ConfigError(f"{where}: a second resolution for `{entry["file"]}`")
        resolved[sha] = resolution
    return Resolutions(resolved, by_record)
