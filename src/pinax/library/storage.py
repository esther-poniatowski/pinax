"""
Index of the files stored by Zotero, by content.

The local API omits the `md5` of many stored attachments, so the content of an attachment is read
from its file under `<storage>/<attachment key>/`. Hashing every stored file is slow, so the index
hashes only the files whose size equals the size of a file looked for.

Classes
-------
StorageIndex
    Content digests of the stored attachment files, restricted to given sizes.
"""

from collections.abc import Iterable
import os
from pathlib import Path

from pinax.hashing import Digests, digest_file
from pinax.library.model import Item


class StorageIndex:
    """
    Content digests of the stored attachment files, restricted to given sizes.

    Parameters
    ----------
    root : Path
        Storage directory, with one sub-directory per attachment key.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._digests: dict[Path, Digests] = {}

    def stored_file(self, attachment: Item) -> Path | None:
        """
        Stored file of an attachment.

        Parameters
        ----------
        attachment : Item
            Attachment item.

        Returns
        -------
        Path | None
            Path of the file under the storage directory, or None when it does not exist.
        """
        name = attachment.get("filename")
        if not name:
            return None
        path = self.root / attachment.key / name
        return path if path.is_file() else None

    def digests(self, path: Path) -> Digests:
        """Digests of a stored file, computed once."""
        if path not in self._digests:
            self._digests[path] = digest_file(path)
        return self._digests[path]

    def by_sha256(self, sizes: Iterable[int]) -> dict[str, str]:
        """
        Attachment key of each stored content whose size is among the given sizes.

        Parameters
        ----------
        sizes : Iterable[int]
            Sizes of the files looked for.

        Returns
        -------
        dict[str, str]
            Attachment key by SHA-256. When two attachments store the same content, the first in
            directory order is kept.
        """
        wanted = set(sizes)
        found: dict[str, str] = {}
        if not self.root.is_dir():
            return found
        with os.scandir(self.root) as directories:
            for directory in sorted(directories, key=lambda entry: entry.name):
                if not directory.is_dir():
                    continue
                with os.scandir(directory.path) as files:
                    for entry in sorted(files, key=lambda file: file.name):
                        if entry.is_file() and entry.stat().st_size in wanted:
                            digest = self.digests(Path(entry.path))
                            found.setdefault(digest.sha256, directory.name)
        return found
