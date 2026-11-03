"""
Snapshots of the library saved to disk, so that later stages read a fixed state.

A snapshot directory holds `probe.json`, `items.json` and `collections.json`. Matching runs on the
snapshot taken before a change, and checks compare the plan with a snapshot taken after it.

Functions
---------
take_snapshot(client, directory) -> dict[str, int]
    Read the library through the local API and save it.
load_snapshot(directory) -> Library
    Load a saved snapshot.
"""

from pathlib import Path

from pinax.artifacts import read_json, write_json
from pinax.errors import ArtifactError
from pinax.library.client import ZoteroClient
from pinax.library.model import Library

ITEMS = "items.json"
COLLECTIONS = "collections.json"
PROBE = "probe.json"


def take_snapshot(client: ZoteroClient, directory: Path) -> dict[str, int]:
    """
    Read the library through the local API and save it.

    Parameters
    ----------
    client : ZoteroClient
        Read-only client.
    directory : Path
        Snapshot directory; existing files are replaced.

    Returns
    -------
    dict[str, int]
        Number of collections and of items read.
    """
    probe = client.probe()
    collections = client.collections()
    items = client.items()
    write_json(directory / PROBE, probe)
    write_json(directory / COLLECTIONS, collections)
    write_json(directory / ITEMS, items)
    return {"collections": len(collections), "items": len(items)}


def load_snapshot(directory: Path) -> Library:
    """
    Load a saved snapshot.

    Parameters
    ----------
    directory : Path
        Snapshot directory.

    Returns
    -------
    Library
        Typed library.

    Raises
    ------
    ArtifactError
        If the directory lacks a file of the snapshot or a file is not a JSON list.
    """
    items = read_json(directory / ITEMS)
    collections = read_json(directory / COLLECTIONS)
    if not isinstance(items, list) or not isinstance(collections, list):
        raise ArtifactError(f"snapshot {directory} must hold JSON lists")
    return Library.from_api(items, collections)
