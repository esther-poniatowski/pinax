"""
Locations of the artifacts that the stages exchange.

Every stage reads the artifacts of earlier stages and writes its own under one workspace directory,
so the names of these files are fixed here and nowhere else.

Classes
-------
Workspace
    Paths of the artifacts under one workspace directory.
"""

from dataclasses import dataclass
from pathlib import Path

from pinax.errors import ArtifactError


@dataclass(frozen=True)
class Workspace:
    """
    Paths of the artifacts under one workspace directory.

    Attributes
    ----------
    root : Path
        Workspace directory.
    """

    root: Path

    def snapshot(self, label: str) -> Path:
        """Directory of the library snapshot named `label`."""
        return self.root / "library" / label

    @property
    def inventory(self) -> Path:
        """Inventory of the sources."""
        return self.root / "inventory.json"

    @property
    def matches(self) -> Path:
        """Matches of the distinct contents with the library."""
        return self.root / "matches.json"

    @property
    def plan(self) -> Path:
        """Change plan."""
        return self.root / "plan.json"

    @property
    def worklist(self) -> Path:
        """Markdown worklist of the manual steps of the plan."""
        return self.root / "worklist.md"

    @property
    def staged(self) -> Path:
        """Default folder of the files to import."""
        return self.root / "staged"

    @property
    def script(self) -> Path:
        """Zotero script generated from the plan."""
        return self.root / "zotero-script.js"

    @property
    def report(self) -> Path:
        """Report of the checks of the plan against the library."""
        return self.root / "check-report.json"

    @property
    def evidence(self) -> Path:
        """Table mapping each source file to its item and citation key."""
        return self.root / "evidence.tsv"

    @property
    def references(self) -> Path:
        """Citation keys of each source folder."""
        return self.root / "references.yml"

    def require(self, path: Path, stage: str) -> Path:
        """
        Return an artifact path, failing when the artifact does not exist.

        Parameters
        ----------
        path : Path
            Artifact expected.
        stage : str
            Command that produces the artifact, named in the error.

        Returns
        -------
        Path
            The same path.

        Raises
        ------
        ArtifactError
            If the artifact is missing.
        """
        if not path.exists():
            raise ArtifactError(f"missing artifact {path}; run `pinax {stage}` first")
        return path
