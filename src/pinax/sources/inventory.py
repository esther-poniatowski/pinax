"""
Inventory of a folder of reference files.

Each file is recorded with its digests, the DOI found on its first pages and the text of those
pages. The name of a file is read by the matching, under the templates of the configuration. Files
with identical bytes form one content, identified by its SHA-256: matching works on contents, and
the exports return to files.

Classes
-------
SourceFile
    One file of the folder.
Content
    The files that share one SHA-256, with the text of their first pages.
Inventory
    Every file and content of the folder.

Functions
---------
build_inventory(config, folders, reader) -> Inventory
    Read the folders and build their inventory.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pinax.config import SourcesConfig
from pinax.errors import ArtifactError
from pinax.hashing import digest_file
from pinax.sources.pdf import PdfReader
from pinax.text import find_doi

INVENTORY_FORMAT = "pinax-inventory/2"


@dataclass(frozen=True)
class SourceFile:
    """
    One file of the folder.

    Attributes
    ----------
    folder : str
        Directory of the file, relative to the root of the sources.
    name : str
        File name.
    size : int
        Size in bytes.
    sha256 : str
        SHA-256 of the content.
    md5 : str
        MD5 of the content.
    doi : str
        First DOI found on the first pages, normalized.
    pdf_title : str
        Title of the PDF metadata.
    """

    folder: str
    name: str
    size: int
    sha256: str
    md5: str
    doi: str = ""
    pdf_title: str = ""

    @property
    def relative(self) -> Path:
        """Path relative to the root of the sources."""
        return Path(self.folder) / self.name

    @property
    def is_pdf(self) -> bool:
        """Whether the file has the extension of a PDF."""
        return self.name.lower().endswith(".pdf")


@dataclass(frozen=True)
class Content:
    """
    The files that share one SHA-256, with the text of their first pages.

    Attributes
    ----------
    sha256 : str
        Identity of the content.
    files : tuple[SourceFile, ...]
        Files holding the content, in inventory order.
    pages : tuple[str, ...]
        Text of the first pages; empty for a non-PDF file or a PDF without a text layer.
    """

    sha256: str
    files: tuple[SourceFile, ...]
    pages: tuple[str, ...] = ()

    @property
    def first(self) -> SourceFile:
        """First file holding the content, whose name the matching reads."""
        return self.files[0]

    @property
    def doi(self) -> str:
        """DOI found on the first pages."""
        return self.first.doi

    @property
    def size(self) -> int:
        """Size of the content in bytes."""
        return self.first.size

    @property
    def folders(self) -> tuple[str, ...]:
        """Distinct folders holding the content, in inventory order."""
        return tuple(dict.fromkeys(file.folder for file in self.files))


class Inventory:
    """
    Every file and content of the folder.

    Parameters
    ----------
    root : Path
        Root of the sources.
    files : list[SourceFile]
        Files in a stable order.
    pages : Mapping[str, list[str]]
        Text of the first pages by SHA-256.
    """

    def __init__(self, root: Path, files: list[SourceFile], pages: Mapping[str, list[str]]) -> None:
        self.root = root
        self.files = files
        self.pages = dict(pages)
        grouped: dict[str, list[SourceFile]] = {}
        for file in files:
            grouped.setdefault(file.sha256, []).append(file)
        self.contents = {
            sha: Content(sha, tuple(group), tuple(self.pages.get(sha, [])))
            for sha, group in grouped.items()
        }

    def __iter__(self) -> Iterator[Content]:
        return iter(self.contents.values())

    def path(self, file: SourceFile) -> Path:
        """Absolute path of a file."""
        return self.root / file.relative

    def to_json(self) -> dict[str, Any]:
        """Serializable form of the inventory."""
        return {
            "format": INVENTORY_FORMAT,
            "root": str(self.root),
            "files": [asdict(file) for file in self.files],
            "pages": self.pages,
        }

    @classmethod
    def from_json(cls, data: Any) -> "Inventory":
        """
        Rebuild an inventory from its serialized form.

        Parameters
        ----------
        data : Any
            Value written by `to_json`.

        Returns
        -------
        Inventory
            The inventory.

        Raises
        ------
        ArtifactError
            If the format tag does not match.
        """
        if not isinstance(data, dict) or data.get("format") != INVENTORY_FORMAT:
            raise ArtifactError(f"not an inventory of format {INVENTORY_FORMAT}")
        files = [SourceFile(**entry) for entry in data["files"]]
        return cls(Path(data["root"]), files, data.get("pages", {}))


def _walk(config: SourcesConfig, folders: Sequence[str]) -> Iterator[Path]:
    """Files under the folders, each once and in path order, without the ignored names."""
    found: set[Path] = set()
    for folder in folders:
        base = config.root / folder
        if not base.is_dir():
            raise ArtifactError(f"source folder not found: {base}")
        found.update(
            path for path in base.rglob("*") if path.is_file() and path.name not in config.ignore
        )
    yield from sorted(found)


def build_inventory(config: SourcesConfig, folders: Sequence[str], reader: PdfReader) -> Inventory:
    """
    Read the folders and build their inventory.

    Parameters
    ----------
    config : SourcesConfig
        Root, ignored names and number of pages.
    folders : Sequence[str]
        Folders relative to the root, `.` for the root; a file under two nested folders is
        recorded once.
    reader : PdfReader
        Extraction of text and title.

    Returns
    -------
    Inventory
        Files in path order; the text of a content is extracted once.
    """
    files: list[SourceFile] = []
    pages: dict[str, list[str]] = {}
    for path in _walk(config, folders):
        digests = digest_file(path)
        doi, title = "", ""
        if path.suffix.lower() == ".pdf":
            if digests.sha256 not in pages:
                pages[digests.sha256] = reader.pages(path, config.pages)
            doi = find_doi("\n".join(pages[digests.sha256]))
            title = reader.title(path)
        files.append(
            SourceFile(
                folder=str(path.parent.relative_to(config.root)),
                name=path.name,
                size=digests.size,
                sha256=digests.sha256,
                md5=digests.md5,
                doi=doi,
                pdf_title=title,
            )
        )
    return Inventory(config.root, files, pages)
