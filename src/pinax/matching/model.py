"""
Types of the matching: how a content was matched, how firmly, and with which outcome.

Classes
-------
Method
    Route that proposed the item of a match.
Verdict
    Confirmation of a candidate by the text of the file.
Status
    Outcome of the matching of one content.
Candidate
    Item proposed for a content by one route.
Match
    Outcome of the matching of one content.
RecordMatch
    Outcome of the matching of one work described by records.

Functions
---------
matches_to_json(matches, snapshot, records) -> dict[str, Any]
    Serializable form of the matches of an inventory.
matches_from_json(data) -> list[Match]
    Rebuild the matches of the contents from their serialized form.
record_matches_from_json(data) -> list[RecordMatch]
    Rebuild the matches of the record works from their serialized form.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pinax.errors import ArtifactError


class Method(StrEnum):
    """Route that proposed the item of a match; `TITLE` matches a record by its title and year."""

    SAME_FILE = "same-file"
    DOI = "doi"
    NAME = "name"
    REVERSE = "reverse"
    TITLE = "title"
    RESOLUTION = "resolution"


class Verdict(StrEnum):
    """
    Confirmation of a candidate by the text of the file.

    `IDENTICAL` holds when the library stores the same bytes; `CONFIRMED` when the opening words
    of the title appear in sequence in the first pages; `REJECTED` when fewer title words than the
    threshold appear; `CHECK` otherwise, including a PDF without a text layer.
    """

    IDENTICAL = "identical"
    CONFIRMED = "confirmed"
    CHECK = "check"
    REJECTED = "rejected"


class Status(StrEnum):
    """
    Outcome of the matching of one content.

    `MATCHED`: the item holds the work of the file. `PREPRINT_OF`: the item holds another version of
    the work, by manual resolution. `CHECK`: a candidate awaits a manual resolution. `ABSENT`: no
    item holds the work.
    """

    MATCHED = "matched"
    PREPRINT_OF = "preprint-of"
    CHECK = "check"
    ABSENT = "absent"


@dataclass(frozen=True)
class Candidate:
    """
    Item proposed for a content by one route.

    Attributes
    ----------
    item : str
        Item key.
    method : Method
        Route that proposed it.
    score : float
        Overlap score of a match by name, 1.0 for the other routes.
    """

    item: str
    method: Method
    score: float = 1.0


@dataclass(frozen=True)
class Match:
    """
    Outcome of the matching of one content.

    Attributes
    ----------
    sha256 : str
        Content matched.
    status : Status
        Outcome.
    item : str
        Item key, empty for an absent content.
    method : Method | None
        Route of the item.
    verdict : Verdict | None
        Confirmation of the item by the text of the file.
    share : float | None
        Share of the title words found in the first pages.
    note : str
        Explanation, such as a resolution note or the titles that the file only cites.
    """

    sha256: str
    status: Status
    item: str = ""
    method: Method | None = None
    verdict: Verdict | None = None
    share: float | None = None
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        """Serializable form of the match."""
        return {
            "sha256": self.sha256,
            "status": self.status.value,
            "item": self.item,
            "method": self.method.value if self.method else None,
            "verdict": self.verdict.value if self.verdict else None,
            "share": self.share,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Match":
        """Rebuild a match from its serialized form."""
        return cls(
            sha256=data["sha256"],
            status=Status(data["status"]),
            item=data.get("item") or "",
            method=Method(data["method"]) if data.get("method") else None,
            verdict=Verdict(data["verdict"]) if data.get("verdict") else None,
            share=data.get("share"),
            note=data.get("note") or "",
        )


@dataclass(frozen=True)
class RecordMatch:
    """
    Outcome of the matching of one work described by records.

    Attributes
    ----------
    identity : str
        Identity of the work.
    refs : tuple[str, ...]
        References of its records, as `refs.bib#3`.
    status : Status
        Outcome.
    item : str
        Item key, empty for an absent work.
    method : Method | None
        Route of the item.
    note : str
        Explanation, such as the disagreements of the records or the candidates left to check.
    """

    identity: str
    refs: tuple[str, ...]
    status: Status
    item: str = ""
    method: Method | None = None
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        """Serializable form of the match."""
        return {
            "identity": self.identity,
            "refs": list(self.refs),
            "status": self.status.value,
            "item": self.item,
            "method": self.method.value if self.method else None,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RecordMatch":
        """Rebuild a match from its serialized form."""
        return cls(
            identity=data["identity"],
            refs=tuple(data["refs"]),
            status=Status(data["status"]),
            item=data.get("item") or "",
            method=Method(data["method"]) if data.get("method") else None,
            note=data.get("note") or "",
        )


MATCHES_FORMAT = "pinax-matches/2"


def matches_to_json(
    matches: list[Match], snapshot: str, records: list[RecordMatch] | None = None
) -> dict[str, Any]:
    """
    Serializable form of the matches of an inventory.

    Parameters
    ----------
    matches : list[Match]
        Matches of the contents, in inventory order.
    snapshot : str
        Label of the library snapshot matched against.
    records : list[RecordMatch] | None
        Matches of the record works, in inventory order.

    Returns
    -------
    dict[str, Any]
        Document with the format tag, the snapshot label, and both lists of matches.
    """
    return {
        "format": MATCHES_FORMAT,
        "snapshot": snapshot,
        "matches": [match.to_json() for match in matches],
        "records": [match.to_json() for match in records or []],
    }


def matches_from_json(data: Any) -> list[Match]:
    """
    Rebuild the matches from their serialized form.

    Parameters
    ----------
    data : Any
        Value written by `matches_to_json`.

    Returns
    -------
    list[Match]
        Matches of the contents, in inventory order.

    Raises
    ------
    ArtifactError
        If the format tag does not match.
    """
    _require_format(data)
    return [Match.from_json(entry) for entry in data["matches"]]


def record_matches_from_json(data: Any) -> list[RecordMatch]:
    """
    Rebuild the matches of the record works from their serialized form.

    Parameters
    ----------
    data : Any
        Value written by `matches_to_json`.

    Returns
    -------
    list[RecordMatch]
        Matches of the record works, in inventory order.

    Raises
    ------
    ArtifactError
        If the format tag does not match.
    """
    _require_format(data)
    return [RecordMatch.from_json(entry) for entry in data.get("records", [])]


def _require_format(data: Any) -> None:
    """Fail unless the data carries the format tag of the matches."""
    if not isinstance(data, dict) or data.get("format") != MATCHES_FORMAT:
        raise ArtifactError(f"not a list of matches of format {MATCHES_FORMAT}")
