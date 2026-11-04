"""
Fake of the Zotero desktop application, for the tests of the connector route.

The fake serves the local API (items, collections, quick search) and the four connector endpoints
that Pinax calls. It reproduces the behaviour that the route must withstand: `saveItems` ignores
its target and files the item into the collection selected in the interface, and `updateSession`
moves the last item of its session. A created item receives a citation key at once, as Better
BibTeX gives one shortly after the creation.
"""

from dataclasses import dataclass, field
import json
from typing import Any
import urllib.parse
import urllib.request

from pinax.errors import LibraryError
from pinax.library.client import Response
from pinax.text import words

COLLECTIONS = [
    ("REVIEW01", "review", None, "C1"),
    ("BACKGR01", "background", "REVIEW01", "C2"),
    ("ELSEWH01", "elsewhere", None, "C3"),
]
"""Key, name, parent key and connector target of each collection of the user library."""


@dataclass
class FakeZotero:  # pylint: disable=too-many-instance-attributes
    """
    Fake of the Zotero desktop application.

    Attributes
    ----------
    items : list[dict[str, Any]]
        Entries of the local API.
    selected : str
        Key of the collection selected in the interface, where `saveItems` files an item.
    ignore_update : bool
        Whether `updateSession` leaves the item in place, as a regression of Zotero would.
    fail_save : bool
        Whether `saveItems` raises, as a timeout would.
    duplicate : bool
        Whether `saveItems` creates two items, as a doubled request would.
    posts : list[str]
        Connector endpoints called, in order.
    """

    items: list[dict[str, Any]] = field(default_factory=list)
    selected: str = "ELSEWH01"
    ignore_update: bool = False
    fail_save: bool = False
    duplicate: bool = False
    posts: list[str] = field(default_factory=list)
    _sessions: dict[str, str] = field(default_factory=dict)
    _created: int = 0

    def collections(self) -> list[dict[str, Any]]:
        """Collection entries of the local API."""
        return [
            {"key": key, "data": {"key": key, "name": name, "parentCollection": parent or False}}
            for key, name, parent, _ in COLLECTIONS
        ]

    def targets(self) -> dict[str, Any]:
        """Body of `getSelectedCollection`: each library, then its collections depth first."""
        levels = {"REVIEW01": 1, "BACKGR01": 2, "ELSEWH01": 1}
        user = [{"id": "L1", "name": "My Library", "level": 0, "recent": True}]
        user += [
            {"id": target, "name": name, "level": levels[key], "filesEditable": True}
            for key, name, _, target in COLLECTIONS
        ]
        group = [{"id": "L3", "name": "Group", "level": 0}, {"id": "C9", "name": "x", "level": 1}]
        return {"libraryID": 1, "libraryName": "My Library", "id": 3, "targets": user + group}

    def _get(self, url: str) -> Response:
        """Serve one GET of the local API."""
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        start = int(query.get("start", ["0"])[0])
        if parsed.path.endswith("/collections"):
            rows = self.collections()
        else:
            rows = self.items
            if "q" in query:
                wanted = set(words(query["q"][0]))
                rows = [e for e in rows if wanted <= set(words(e["data"].get("title", "")))]
        page = rows[start : start + 100]
        return Response(200, {"Total-Results": str(len(rows))}, json.dumps(page))

    def _save(self, payload: dict[str, Any]) -> Response:
        """Serve `saveItems`: file each item into the selected collection, ignoring any target."""
        if self.fail_save:
            raise LibraryError("cannot reach the connector: timed out")
        for item in payload["items"] * (2 if self.duplicate else 1):
            self._created += 1
            key = f"NEW{self._created:05d}"
            data = {k: v for k, v in item.items() if k not in ("creators", "tags", "attachments")}
            data.update(key=key, collections=[self.selected], citationKey=f"made{self._created}")
            data["creators"] = [{**c, "creatorType": "author"} for c in item["creators"]]
            self.items.append({"key": key, "data": data})
            self._sessions[payload["sessionID"]] = key
        return Response(201, {}, "")

    def _update(self, payload: dict[str, Any]) -> Response:
        """Serve `updateSession`: move the last item of the session to the target."""
        key = self._sessions[payload["sessionID"]]
        target = {target: key for key, _, _, target in COLLECTIONS}[payload["target"]]
        if not self.ignore_update:
            for entry in self.items:
                if entry["key"] == key:
                    entry["data"]["collections"] = [target]
        return Response(200, {}, "")

    def transport(self, request: urllib.request.Request, timeout: float) -> Response:
        """Transport serving the requests of Pinax."""
        del timeout
        url = request.full_url
        if request.get_method() == "GET":
            return self._get(url)
        endpoint = url.rsplit("/", 1)[-1]
        self.posts.append(endpoint)
        body = request.data
        payload = json.loads(body.decode("utf-8")) if isinstance(body, bytes) else {}
        if endpoint == "getSelectedCollection":
            return Response(200, {}, json.dumps(self.targets()))
        if endpoint == "ping":
            return Response(200, {}, json.dumps({"prefs": {"version": "test"}}))
        if endpoint == "saveItems":
            return self._save(payload)
        if endpoint == "updateSession":
            return self._update(payload)
        raise LibraryError(f"the fake serves no endpoint {endpoint}")
