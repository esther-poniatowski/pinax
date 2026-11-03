"""
Extraction of the text and the title of a PDF.

Classes
-------
PdfReader
    Protocol of the extraction used by the inventory and the checks.
PopplerReader
    Extraction through the Poppler tools `pdftotext` and `pdfinfo`.
"""

from pathlib import Path
import shutil
import subprocess  # nosec B404
import sys
from typing import Protocol

from pinax.errors import ConfigError


class PdfReader(Protocol):
    """Protocol of the extraction used by the inventory and the checks."""

    def pages(self, path: Path, count: int) -> list[str]:
        """
        Text of the opening pages of a PDF.

        Parameters
        ----------
        path : Path
            PDF file.
        count : int
            Number of opening pages.

        Returns
        -------
        list[str]
            Text of each page, empty strings for a PDF without a text layer.
        """

    def title(self, path: Path) -> str:
        """Title recorded in the metadata of a PDF, empty when absent."""


def _locate(tool: str) -> str | None:
    """Tool beside the running interpreter, as installed in its environment, else on the path."""
    sibling = Path(sys.executable).parent / tool
    return str(sibling) if sibling.is_file() else shutil.which(tool)


class PopplerReader:
    """
    Extraction through the Poppler tools `pdftotext` and `pdfinfo`.

    Parameters
    ----------
    timeout : float
        Timeout of each call, in seconds; a PDF that exceeds it yields no text.

    Raises
    ------
    ConfigError
        If `pdftotext` or `pdfinfo` is neither beside the interpreter nor on the path.
    """

    def __init__(self, timeout: float = 60.0) -> None:
        tools = {tool: _locate(tool) for tool in ("pdftotext", "pdfinfo")}
        missing = [tool for tool, path in tools.items() if path is None]
        if missing:
            raise ConfigError(
                f"missing {", ".join(missing)}: install poppler in the environment of pinax"
            )
        self._pdftotext = str(tools["pdftotext"])
        self._pdfinfo = str(tools["pdfinfo"])
        self._timeout = timeout

    def _run(self, arguments: list[str]) -> str:
        """Standard output of a tool, empty when the tool exceeds the timeout."""
        try:
            result = subprocess.run(  # nosec B603
                arguments, capture_output=True, text=True, timeout=self._timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return ""
        return result.stdout

    def pages(self, path: Path, count: int) -> list[str]:
        """
        Text of the opening pages of a PDF.

        Parameters
        ----------
        path : Path
            PDF file.
        count : int
            Number of opening pages.

        Returns
        -------
        list[str]
            Text of each page; `pdftotext` separates pages by form feeds.
        """
        text = self._run([self._pdftotext, "-l", str(count), "-enc", "UTF-8", str(path), "-"])
        pages = text.split("\f")
        return pages[:count] if text.strip() else []

    def title(self, path: Path) -> str:
        """Title recorded in the metadata of a PDF, empty when absent."""
        for line in self._run([self._pdfinfo, str(path)]).splitlines():
            if line.startswith("Title:"):
                return line.split(":", 1)[1].strip()
        return ""
