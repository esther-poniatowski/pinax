"""
Inventory of a folder of reference files.

Each file is recorded with its digests, the year that opens its name, the DOI found on its first
pages and the text of those pages. Files with identical bytes form one content, identified by its
SHA-256: matching works on contents, and the exports return to files.

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
build_inventory(config, reader) -> Inventory
    Read the folder and build its inventory.
"""

from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from pinax.config import SourcesConfig
from pinax.errors import ArtifactError
from pinax.hashing import digest_file
from pinax.sources.pdf import PdfReader
from pinax.text import find_doi

INVENTORY_FORMAT = "pinax-inventory/1"
_YEAR_PREFIX = re.compile(r"^((?:1[5-9]|20)\d\d)(?!\d)")


@dataclass(frozen=True)
class SourceFile:  # pylint: disable=too-many-instance-attributes
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
    year : str
        Year that opens the file name, empty when the name does not open on a year.
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
    year: str = ""
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


def _walk(config: SourcesConfig) -> Iterator[Path]:
    """Files under the configured folders, in path order, without the ignored names."""
    bases = [config.root / folder for folder in config.folders] or [config.root]
    for base in bases:
        if not base.is_dir():
            raise ArtifactError(f"source folder not found: {base}")
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.name not in config.ignore:
                yield path


def build_inventory(config: SourcesConfig, reader: PdfReader) -> Inventory:
    """
    Read the folder and build its inventory.

    Parameters
    ----------
    config : SourcesConfig
        Root, folders and number of pages.
    reader : PdfReader
        Extraction of text and title.

    Returns
    -------
    Inventory
        Files in path order; the text of a content is extracted once.
    """
    files: list[SourceFile] = []
    pages: dict[str, list[str]] = {}
    for path in _walk(config):
        digests = digest_file(path)
        year = _YEAR_PREFIX.match(path.name)
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
                year=year.group(1) if year else "",
                doi=doi,
                pdf_title=title,
            )
        )
    return Inventory(config.root, files, pages)
