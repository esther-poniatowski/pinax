"""
Read-only client of the Zotero desktop application on the loopback interface.

The client reads the local API, pings the connector and asks Better BibTeX for citation keys. It
sends no write request: the local API is only ever read with GET, and the two POST requests it
sends (`/connector/ping` and the JSON-RPC method `item.citationkey`) change no state.

Classes
-------
Transport
    Protocol of the function that performs one HTTP request.
Response
    Status, headers and body of one HTTP response.
ZoteroClient
    Read-only client of one Zotero desktop application.

Functions
---------
urllib_transport(request, timeout) -> Response
    Transport based on `urllib`, the default.
require_loopback(url) -> str
    Validate that a base URL points at the loopback interface.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from pinax.errors import LibraryError

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
"""Hosts accepted for the desktop application, whose local API does not authenticate readers."""

API_VERSION_HEADER = {"Zotero-API-Version": "3"}
CONNECTOR_HEADERS = {"Content-Type": "application/json", "X-Zotero-Connector-API-Version": "3"}
PAGE_SIZE = 100
"""Largest page that the local API returns."""


@dataclass(frozen=True)
class Response:
    """
    Status, headers and body of one HTTP response.

    Attributes
    ----------
    status : int
        HTTP status.
    headers : dict[str, str]
        Response headers.
    body : str
        Decoded body.
    """

    status: int
    headers: dict[str, str]
    body: str


Transport = Callable[[urllib.request.Request, float], Response]
"""Function that performs one request with a timeout in seconds."""


def urllib_transport(request: urllib.request.Request, timeout: float) -> Response:
    """
    Transport based on `urllib`, the default.

    Parameters
    ----------
    request : urllib.request.Request
        Prepared request.
    timeout : float
        Timeout in seconds.

    Returns
    -------
    Response
        Response of the server.

    Raises
    ------
    LibraryError
        If the server cannot be reached or answers with an HTTP error.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout) as handle:  # nosec B310
            return Response(
                status=handle.status,
                headers=dict(handle.headers),
                body=handle.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as error:
        raise LibraryError(f"{request.full_url} answered {error.code} {error.reason}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise LibraryError(
            f"cannot reach {request.full_url}: {error}; is the Zotero application running?"
        ) from error


def require_loopback(url: str) -> str:
    """
    Validate that a base URL points at the loopback interface.

    Parameters
    ----------
    url : str
        Base URL of the desktop application.

    Returns
    -------
    str
        The URL without a trailing slash.

    Raises
    ------
    LibraryError
        If the scheme is not HTTP or the host is not a loopback host.

    Examples
    --------
    >>> require_loopback("http://127.0.0.1:23119/")
    'http://127.0.0.1:23119'
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise LibraryError(
            f"refusing {url}: the local API must be reached on the loopback interface only"
        )
    return url.rstrip("/")


class ZoteroClient:
    """
    Read-only client of one Zotero desktop application.

    Parameters
    ----------
    base_url : str
        Base URL of the application, on a loopback host.
    transport : Transport
        Function performing the requests; tests inject a fake.
    timeout : float
        Timeout of each request, in seconds.
    """

    def __init__(
        self, base_url: str, transport: Transport = urllib_transport, timeout: float = 60.0
    ) -> None:
        self.base_url = require_loopback(base_url)
        self._transport = transport
        self._timeout = timeout

    def _get(self, path: str) -> Response:
        """GET a path of the local API."""
        request = urllib.request.Request(
            f"{self.base_url}/api/{path}", headers=API_VERSION_HEADER, method="GET"
        )
        return self._transport(request, self._timeout)

    def _post(self, path: str, payload: Any, headers: dict[str, str]) -> Response:
        """POST a JSON payload to a read-only endpoint outside the local API."""
        request = urllib.request.Request(
            f"{self.base_url}/{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._transport(request, self._timeout)

    def probe(self) -> dict[str, Any]:
        """
        Record the versions reported by the local API and the connector.

        Returns
        -------
        dict[str, Any]
            `api`: Zotero headers of `/api/` and the start of its body; `connector`: the status
            and the parsed body of `/connector/ping`, or the error met.
        """
        api = self._get("")
        record: dict[str, Any] = {
            "api": {
                "status": api.status,
                "headers": {
                    name: value
                    for name, value in api.headers.items()
                    if "zotero" in name.lower() or "api" in name.lower()
                },
                "body": api.body[:500],
            }
        }
        try:
            ping = self._post("connector/ping", {}, CONNECTOR_HEADERS)
            record["connector"] = {"status": ping.status, "body": _maybe_json(ping.body)}
        except LibraryError as error:
            record["connector"] = {"error": str(error)}
        return record

    def paged(self, path: str) -> list[dict[str, Any]]:
        """
        Read every entry of a list endpoint of the local API, page by page.

        Parameters
        ----------
        path : str
            Path under `/api/`, such as `users/0/items`.

        Returns
        -------
        list[dict[str, Any]]
            Entries of every page, in order.

        Raises
        ------
        LibraryError
            If a page is not a JSON list.
        """
        rows: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        while True:
            response = self._get(
                f"{path}{separator}format=json&limit={PAGE_SIZE}&start={len(rows)}"
            )
            page = _maybe_json(response.body)
            if not isinstance(page, list):
                raise LibraryError(f"/api/{path} did not return a JSON list")
            rows.extend(page)
            total = int(response.headers.get("Total-Results", len(rows)))
            if not page or len(rows) >= total:
                return rows

    def items(self) -> list[dict[str, Any]]:
        """Every item of the user library, attachments and trashed items included."""
        return self.paged("users/0/items")

    def collections(self) -> list[dict[str, Any]]:
        """Every collection of the user library."""
        return self.paged("users/0/collections")

    def citation_keys(self, keys: Sequence[str]) -> dict[str, str]:
        """
        Ask Better BibTeX for the citation keys of items.

        Parameters
        ----------
        keys : Sequence[str]
            Item keys.

        Returns
        -------
        dict[str, str]
            Citation key of each item that Better BibTeX knows.

        Raises
        ------
        LibraryError
            If Better BibTeX answers with an error or an unexpected shape.
        """
        payload = {"jsonrpc": "2.0", "method": "item.citationkey", "params": [list(keys)], "id": 1}
        response = self._post(
            "better-bibtex/json-rpc", payload, {"Content-Type": "application/json"}
        )
        body = _maybe_json(response.body)
        if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
            raise LibraryError(f"unexpected answer of Better BibTeX: {response.body[:200]}")
        return {str(k): str(v) for k, v in body["result"].items() if v}


def _maybe_json(body: str) -> Any:
    """Decoded JSON body, or the raw body when it is not JSON."""
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body
