"""
Digests of files, shared by the inventory of sources and the index of the Zotero storage.

Classes
-------
Digests
    Size, SHA-256 and MD5 of one file.

Functions
---------
digest_file(path) -> Digests
    Read a file once and compute its digests.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path

_CHUNK = 1 << 20


@dataclass(frozen=True)
class Digests:
    """
    Size, SHA-256 and MD5 of one file.

    Attributes
    ----------
    size : int
        Size in bytes.
    sha256 : str
        Hexadecimal SHA-256, the identity of a content across pinax.
    md5 : str
        Hexadecimal MD5, the digest that Zotero records for a stored attachment.
    """

    size: int
    sha256: str
    md5: str


def digest_file(path: Path) -> Digests:
    """
    Read a file once and compute its digests.

    Parameters
    ----------
    path : Path
        File to read.

    Returns
    -------
    Digests
        Size and digests of the file.
    """
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            sha256.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return Digests(size=size, sha256=sha256.hexdigest(), md5=md5.hexdigest())
