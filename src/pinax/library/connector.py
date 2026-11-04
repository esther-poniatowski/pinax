"""
Creation of items through the connector of the Zotero desktop application, one item per session.

The connector route is the only write route of Pinax. It follows the serial transaction that the
workflow rules of the researcher approve: the connector ignores the target given to `saveItems`, so
each item is posted in a session of its own and then retargeted through `updateSession`, which
moves the last item of a session. Each item is read back through the local API before the next
one, and the run stops at the first failed verification or ambiguous outcome. The search made
before each write makes a second run harmless: an item already created is found and skipped.

Classes
-------
Connector
    Write endpoints of the connector, and the list of its targets.
Outcome
    Outcome of one creation.
Creation
    Result of one creation.
CreationRun
    Serial creation of the items of a plan.

Functions
---------
numeric_targets(selected, library) -> dict[str, str]
    Connector target of each collection of the library, by collection key.
"""

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import re
import time
from typing import Any
import uuid

from pinax.errors import LibraryError
from pinax.library.client import CONNECTOR_HEADERS, LoopbackService, ZoteroClient
from pinax.library.model import Item, Library
from pinax.plans.model import CreateOp
from pinax.text import words

_TARGET_ID = re.compile(r"^[LC]\d+$")
USER_LIBRARY = "L1"
"""Connector identifier of the user library, whose collections the local API lists."""
SEARCH_WORDS = 8
"""Opening title words sent as the query of the search that precedes and follows a write."""


class Connector(LoopbackService):
    """
    Write endpoints of the connector, and the list of its targets.

    The base URL, the transport and the timeout are those of `LoopbackService`.
    """

    def _call(self, endpoint: str, payload: Any) -> tuple[int, Any]:
        """POST a JSON payload to an endpoint of the connector; returns the status and the body."""
        response = self._post(f"connector/{endpoint}", payload, CONNECTOR_HEADERS)
        try:
            return response.status, json.loads(response.body) if response.body else None
        except json.JSONDecodeError:
            return response.status, response.body

    def ping(self) -> Any:
        """Body of `/connector/ping`, which states the versions of the connector."""
        return self._call("ping", {})[1]

    def selected_collection(self) -> Any:
        """Body of `/connector/getSelectedCollection`, which lists the targets."""
        return self._call("getSelectedCollection", {})[1]

    def save_items(self, items: list[dict[str, Any]], session: str) -> int:
        """Post items in a session; returns the HTTP status."""
        return self._call("saveItems", {"items": items, "sessionID": session})[0]

    def update_session(self, session: str, target: str) -> int:
        """Retarget the last item of a session; returns the HTTP status."""
        return self._call("updateSession", {"sessionID": session, "target": target})[0]


def _target_entries(selected: Any) -> list[dict[str, Any]]:
    """Validated list `targets` of the selected-collection response."""
    targets = selected.get("targets") if isinstance(selected, dict) else None
    if not isinstance(targets, list):
        raise LibraryError("the connector lists no targets; its response shape has changed")
    for entry in targets:
        valid = (
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and _TARGET_ID.match(entry["id"])
            and isinstance(entry.get("name"), str)
            and isinstance(entry.get("level"), int)
        )
        if not valid:
            raise LibraryError(f"unexpected connector target: {str(entry)[:120]}")
    return targets


def numeric_targets(selected: Any, library: Library) -> dict[str, str]:
    """
    Connector target of each collection of the library, by collection key.

    The connector lists each library followed by its collections, depth first, each with its
    level. The path of each collection is rebuilt from the levels, and the paths of the user
    library must equal the paths of the snapshot: a difference stops the creation before any write.

    Parameters
    ----------
    selected : Any
        Body of `/connector/getSelectedCollection`.
    library : Library
        Snapshot of the library.

    Returns
    -------
    dict[str, str]
        Target such as `C37` of each collection whose path is unique in the library.

    Raises
    ------
    LibraryError
        If the response has an unexpected shape, or its paths differ from those of the snapshot.
    """
    by_path: dict[str, list[str]] = {}
    stack: list[str] = []
    inside = False
    for entry in _target_entries(selected):
        if entry["id"].startswith("L"):
            inside = entry["id"] == USER_LIBRARY
            stack = []
            continue
        if inside:
            stack = stack[: entry["level"] - 1] + [entry["name"]]
            by_path.setdefault("/".join(stack), []).append(entry["id"])
    known = {library.collection_path(key) for key in library.collections}
    if set(by_path) != known or sum(len(ids) for ids in by_path.values()) != len(
        library.collections
    ):
        raise LibraryError(
            "the collections listed by the connector differ from the snapshot; take a new snapshot"
        )
    found = {}
    for key in library.collections:
        ids = by_path[library.collection_path(key)]
        if len(ids) == 1:
            found[key] = ids[0]
    return found


class Outcome(StrEnum):
    """
    Outcome of one creation.

    `CREATED`: the item was created and verified. `EXISTS`: an item already holds the identity, so
    nothing was written. `FAILED`: the item was written, and a verification failed.
    `AMBIGUOUS`: a request had no clear outcome, so the library must be read before any retry.
    """

    CREATED = "created"
    EXISTS = "exists"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Creation:
    """
    Result of one creation.

    Attributes
    ----------
    identity : str
        Identity of the work.
    outcome : Outcome
        Outcome.
    item : str
        Key of the created or existing item, empty when none was found.
    detail : str
        Evidence of the outcome.
    """

    identity: str
    outcome: Outcome
    item: str = ""
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        """Serializable form of the result."""
        return {**asdict(self), "outcome": self.outcome.value}


class CreationRun:
    """
    Serial creation of the items of a plan.

    Parameters
    ----------
    client : ZoteroClient
        Reader of the local API, used by the searches before and after each write.
    connector : Connector
        Write endpoints of the connector.
    targets : dict[str, str]
        Connector target of each destination key, from `numeric_targets`.
    sleep : Callable[[float], None]
        Pause between two readings of an item; tests inject a function that does not wait.
    attempts : int
        Readings of an item after its write, before the verification fails.
    """

    def __init__(
        self,
        client: ZoteroClient,
        connector: Connector,
        targets: dict[str, str],
        *,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 5,
    ) -> None:
        self._client = client
        self._connector = connector
        self._targets = targets
        self._sleep = sleep
        self._attempts = attempts

    def _search(self, op: CreateOp) -> list[Item]:
        """Live items holding the identity of a creation, searched by the opening title words."""
        query = " ".join(words(op.title)[:SEARCH_WORDS])
        entries = self._client.search(query)
        found = (Item.from_api(entry) for entry in entries)
        return [item for item in found if item.holds_work(op.doi, op.title)]

    def _verify(self, op: CreateOp, before: set[str]) -> Creation:
        """Read the created item back until it verifies, or until the attempts run out."""
        problem = "no new item holds the identity"
        for attempt in range(self._attempts):
            if attempt:
                self._sleep(1.0)
            found = self._search(op)
            new = [item for item in found if item.key not in before]
            if len(found) > 1:
                keys = ", ".join(item.key for item in found)
                return Creation(op.identity, Outcome.FAILED, new[0].key if new else "", keys)
            if not new:
                continue
            item = new[0]
            if " ".join(words(item.title)) != " ".join(words(op.title)):
                problem = f"{item.key} carries the title `{item.title[:60]}`"
            elif op.destination not in item.collections:
                problem = f"{item.key} is not in the destination {op.destination}"
            else:
                return Creation(op.identity, Outcome.CREATED, item.key, "verified")
        return Creation(op.identity, Outcome.FAILED, "", problem)

    def create(self, op: CreateOp) -> Creation:
        """
        Create one item, after a search for its identity, and verify it.

        Parameters
        ----------
        op : CreateOp
            Creation of the plan.

        Returns
        -------
        Creation
            `EXISTS` without any write when an item holds the identity; otherwise the outcome of
            the write and of its verification.
        """
        target = self._targets.get(op.destination)
        if target is None:
            return Creation(op.identity, Outcome.FAILED, "", "no unique connector target")
        existing = self._search(op)
        if existing:
            item = existing[0]
            where = ", ".join(item.collections) or "no collection"
            return Creation(op.identity, Outcome.EXISTS, item.key, f"held already, in {where}")
        session = str(uuid.uuid4())
        try:
            saved = self._connector.save_items([op.item], session)
            moved = self._connector.update_session(session, target)
        except LibraryError as error:
            return Creation(op.identity, Outcome.AMBIGUOUS, "", str(error))
        if saved not in (200, 201) or moved not in (200, 201):
            detail = f"saveItems answered {saved}, updateSession {moved}"
            return Creation(op.identity, Outcome.AMBIGUOUS, "", detail)
        return self._verify(op, {item.key for item in existing})

    def run(
        self,
        creations: Sequence[CreateOp],
        limit: int | None = None,
        record: Callable[[list[Creation]], None] = lambda results: None,
    ) -> list[Creation]:
        """
        Create the items of a plan in order, stopping at the first failure or ambiguous outcome.

        Parameters
        ----------
        creations : Sequence[CreateOp]
            Creations of the plan.
        limit : int | None
            Largest number of items to create; None for every item.
        record : Callable[[list[Creation]], None]
            Called with the results after each creation, so that a log survives an interruption.

        Returns
        -------
        list[Creation]
            One result per creation attempted.
        """
        results: list[Creation] = []
        created = 0
        for op in creations:
            if limit is not None and created >= limit:
                break
            result = self.create(op)
            results.append(result)
            record(results)
            if result.outcome is Outcome.CREATED:
                created += 1
            elif result.outcome in (Outcome.FAILED, Outcome.AMBIGUOUS):
                break
        return results
