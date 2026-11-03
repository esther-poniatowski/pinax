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

Functions
---------
matches_to_json(matches, snapshot) -> dict[str, Any]
    Serializable form of the matches of an inventory.
matches_from_json(data) -> list[Match]
    Rebuild the matches from their serialized form.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pinax.errors import ArtifactError


class Method(StrEnum):
    """Route that proposed the item of a match."""

    SAME_FILE = "same-file"
    DOI = "doi"
    NAME = "name"
    REVERSE = "reverse"
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


MATCHES_FORMAT = "pinax-matches/1"


def matches_to_json(matches: list[Match], snapshot: str) -> dict[str, Any]:
    """
    Serializable form of the matches of an inventory.

    Parameters
    ----------
    matches : list[Match]
        Matches in inventory order.
    snapshot : str
        Label of the library snapshot matched against.

    Returns
    -------
    dict[str, Any]
        Document with the format tag, the snapshot label and the matches.
    """
    return {
        "format": MATCHES_FORMAT,
        "snapshot": snapshot,
        "matches": [match.to_json() for match in matches],
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
        Matches in inventory order.

    Raises
    ------
    ArtifactError
        If the format tag does not match.
    """
    if not isinstance(data, dict) or data.get("format") != MATCHES_FORMAT:
        raise ArtifactError(f"not a list of matches of format {MATCHES_FORMAT}")
    return [Match.from_json(entry) for entry in data["matches"]]
