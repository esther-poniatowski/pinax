"""
Location of the item that holds an imported file.

Zotero renames a PDF after it retrieves the metadata, so an imported file is found by its content,
never by its name: first by the MD5 that the attachment records, then, since the local API omits
that MD5 for many attachments, by hashing the stored files whose size equals the size of the file.

Classes
-------
ImportLocator
    Attachment holding the file of each import of a plan.
"""

from collections.abc import Sequence

from pinax.library.model import Item, Library
from pinax.library.storage import StorageIndex
from pinax.plans.model import ImportOp


class ImportLocator:
    """
    Attachment holding the file of each import of a plan.

    Parameters
    ----------
    library : Library
        Snapshot taken after the import.
    storage : StorageIndex
        Index of the stored files.
    """

    def __init__(self, library: Library, storage: StorageIndex) -> None:
        self._library = library
        self._storage = storage

    def locate(self, imports: Sequence[ImportOp]) -> dict[str, Item]:
        """
        Attachment holding the file of each import.

        Parameters
        ----------
        imports : Sequence[ImportOp]
            Imports of a plan.

        Returns
        -------
        dict[str, Item]
            Live attachment by work identity; an import whose file no live attachment stores is
            absent from the mapping.
        """
        by_md5: dict[str, Item] = {}
        for item in self._library.live():
            if item.item_type == "attachment" and item.get("md5"):
                by_md5.setdefault(item.get("md5"), item)
        found: dict[str, Item] = {}
        pending: list[ImportOp] = []
        for op in imports:
            if op.file.md5 in by_md5:
                found[op.work_id] = by_md5[op.file.md5]
            else:
                pending.append(op)
        if pending:
            stored = self._storage.by_sha256(op.file.size for op in pending)
            for op in pending:
                attachment = self._library.get_live(stored.get(op.file.sha256, ""))
                if attachment is not None:
                    found[op.work_id] = attachment
        return found
