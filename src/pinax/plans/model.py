"""
The change plan: the contract between the plan builder, the script writer and the checks.

Nothing writes to the library without a plan, and the checks read the same plan back. A plan holds
the destination collections of its targets, and five lists of operations:

- imports: works that no item holds, each imported from one staged file into one destination;
- attachments: PDFs to attach to existing items without one;
- filings: existing items to add to a destination collection;
- corrections: fields, types and creators to correct;
- skipped: works that cannot be imported, with the reason.

Classes
-------
Destination
    Collection receiving the filed and imported items of one or more folders.
FileRef
    Source file of an operation, identified by its content.
ImportOp, AttachOp, FileOp, CorrectOp, SkippedWork
    The operations of a plan.
CreatorSpec
    One creator of a correction.
ChangePlan
    Complete plan.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from pinax.errors import ArtifactError

PLAN_FORMAT = "pinax-plan/2"


@dataclass(frozen=True)
class Destination:
    """
    Collection receiving the filed and imported items of one or more folders.

    Attributes
    ----------
    key : str
        Collection key.
    name : str
        Collection name, checked by the script before any write.
    path : str
        Full path of the collection, for the reader of the plan.
    scope : str
        Key of the collection whose sub-tree counts as filed for this destination.
    scope_path : str
        Full path of the scope, for the reader of the plan.
    """

    key: str
    name: str
    path: str
    scope: str
    scope_path: str


@dataclass(frozen=True)
class FileRef:
    """
    Source file of an operation, identified by its content.

    Attributes
    ----------
    path : str
        Absolute path of the source file.
    sha256 : str
        SHA-256 of the content.
    md5 : str
        MD5 of the content, the digest that Zotero records.
    size : int
        Size in bytes.
    """

    path: str
    sha256: str
    md5: str
    size: int


@dataclass(frozen=True)
class ImportOp:
    """
    Work to import from one staged file.

    Attributes
    ----------
    work_id : str
        Identity of the work (`doi:` or `sha256:`).
    doi : str
        DOI of the work, empty when unknown.
    file : FileRef
        File to import, the largest PDF of the work.
    staged_name : str
        Name of the copy in the staging folder, unique within it.
    members : tuple[str, ...]
        SHA-256 of every content of the work.
    destination : str
        Key of the collection into which the staged file is dropped: the destination of the
        folder of the imported file.
    also : tuple[str, ...]
        Keys of the other destinations of the folders of the work. The item does not exist before
        the drop, so the next plan files it there.
    """

    work_id: str
    doi: str
    file: FileRef
    staged_name: str
    members: tuple[str, ...]
    destination: str
    also: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttachOp:
    """
    PDF to attach to an existing item without one.

    Attributes
    ----------
    item : str
        Item key.
    citation_key : str
        Citation key of the item, for the reader.
    title : str
        Title of the item, for the reader.
    file : FileRef
        File to attach.
    """

    item: str
    citation_key: str
    title: str
    file: FileRef


@dataclass(frozen=True)
class FileOp:
    """
    Existing item to add to a destination collection.

    Attributes
    ----------
    item : str
        Item key.
    citation_key : str
        Citation key, for the reader.
    title : str
        Title, for the reader.
    destination : str
        Key of the collection receiving the item.
    current : tuple[str, ...]
        Paths of the collections holding the item now; it stays in them.
    """

    item: str
    citation_key: str
    title: str
    destination: str
    current: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreatorSpec:
    """
    One creator of a correction.

    Attributes
    ----------
    last_name : str
        Last name, or the full name of an institution.
    first_name : str
        First name, empty for an institution.
    creator_type : str
        Zotero creator type, such as `author` or `contributor`.
    """

    last_name: str
    first_name: str = ""
    creator_type: str = "author"


@dataclass(frozen=True)
class CorrectOp:
    """
    Correction of the record of an existing item.

    A type change drops the fields that the new type lacks, so the script reads `carry` and
    `preserve` before it changes the type.

    Attributes
    ----------
    item : str
        Item key.
    item_type : str
        New item type, empty to keep the type.
    fields : dict[str, str]
        Fields to set after the type change.
    creators : tuple[CreatorSpec, ...] | None
        Creators replacing the current ones, None to keep them.
    carry : dict[str, str]
        Field of the old type copied into a field of the new type when that field is empty, such as
        `publicationTitle` into `bookTitle`.
    preserve : tuple[str, ...]
        Fields kept across the type change; a field invalid for the new type is written into
        `extra` as `Name: value`.
    note : str
        Reason of the correction, for the reader.
    """

    item: str
    item_type: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    creators: tuple[CreatorSpec, ...] | None = None
    carry: dict[str, str] = field(default_factory=dict)
    preserve: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class SkippedWork:
    """
    Work that cannot be imported, with the reason.

    Attributes
    ----------
    work_id : str
        Identity of the work.
    reason : str
        Why it is skipped.
    files : tuple[str, ...]
        Paths of its files, relative to the sources.
    """

    work_id: str
    reason: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class ChangePlan:
    """
    Complete plan.

    Attributes
    ----------
    destinations : tuple[Destination, ...]
        Collections receiving filed and imported items, each with the scope that counted as filed
        when the plan was built.
    imports, attachments, filings, corrections, skipped
        Operations of the plan.
    """

    destinations: tuple[Destination, ...]
    imports: tuple[ImportOp, ...] = ()
    attachments: tuple[AttachOp, ...] = ()
    filings: tuple[FileOp, ...] = ()
    corrections: tuple[CorrectOp, ...] = ()
    skipped: tuple[SkippedWork, ...] = ()

    def destination(self, key: str) -> Destination:
        """
        Destination of a collection key.

        Raises
        ------
        ArtifactError
            If no destination of the plan has the key.
        """
        for destination in self.destinations:
            if destination.key == key:
                return destination
        raise ArtifactError(f"the plan has no destination {key}")

    def script_items(self) -> list[str]:
        """Keys of every existing item that the script touches, in plan order, without repeats."""
        keys = [op.item for op in self.attachments] + [op.item for op in self.filings]
        keys += [op.item for op in self.corrections]
        return list(dict.fromkeys(keys))

    def to_json(self) -> dict[str, Any]:
        """Serializable form of the plan."""
        return {"format": PLAN_FORMAT, **asdict(self)}

    @classmethod
    def from_json(cls, data: Any) -> "ChangePlan":
        """
        Rebuild a plan from its serialized form.

        Parameters
        ----------
        data : Any
            Value written by `to_json`.

        Returns
        -------
        ChangePlan
            The plan.

        Raises
        ------
        ArtifactError
            If the format tag does not match or an operation is malformed.
        """
        if not isinstance(data, dict) or data.get("format") != PLAN_FORMAT:
            raise ArtifactError(f"not a change plan of format {PLAN_FORMAT}")
        try:
            return cls(
                destinations=tuple(Destination(**entry) for entry in data["destinations"]),
                imports=tuple(
                    ImportOp(
                        work_id=op["work_id"],
                        doi=op["doi"],
                        file=FileRef(**op["file"]),
                        staged_name=op["staged_name"],
                        members=tuple(op["members"]),
                        destination=op["destination"],
                        also=tuple(op.get("also", [])),
                    )
                    for op in data.get("imports", [])
                ),
                attachments=tuple(
                    AttachOp(**{**op, "file": FileRef(**op["file"])})
                    for op in data.get("attachments", [])
                ),
                filings=tuple(
                    FileOp(**{**op, "current": tuple(op.get("current", []))})
                    for op in data.get("filings", [])
                ),
                corrections=tuple(_correction(op) for op in data.get("corrections", [])),
                skipped=tuple(
                    SkippedWork(op["work_id"], op["reason"], tuple(op["files"]))
                    for op in data.get("skipped", [])
                ),
            )
        except (KeyError, TypeError) as error:
            raise ArtifactError(f"malformed change plan: {error}") from error


def _correction(op: dict[str, Any]) -> CorrectOp:
    """Correction rebuilt from its serialized form."""
    creators = op.get("creators")
    return CorrectOp(
        item=op["item"],
        item_type=op.get("item_type", ""),
        fields=dict(op.get("fields", {})),
        creators=None if creators is None else tuple(CreatorSpec(**c) for c in creators),
        carry=dict(op.get("carry", {})),
        preserve=tuple(op.get("preserve", [])),
        note=op.get("note", ""),
    )
