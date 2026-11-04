"""
Staging of the files to import in folders that hold only them.

The researcher drops the files of one sub-folder into its destination collection: a drop targets
one collection, so the staging folder holds one sub-folder per destination. A folder that holds
anything else would import that too, so staging refuses a folder that is not empty.

Functions
---------
subfolder(destination) -> str
    Name of the sub-folder of a destination.
stage(plan, folder) -> int
    Copy the file of each import into the sub-folder of its destination and verify each copy.
"""

from pathlib import Path
import re
import shutil

from pinax.errors import PlanError
from pinax.hashing import digest_file
from pinax.plans.model import ChangePlan, Destination

_UNSAFE = re.compile(r"[/\\:]+")


def subfolder(destination: Destination) -> str:
    """
    Name of the sub-folder of a destination: its key, then its name without path separators.

    Examples
    --------
    >>> subfolder(Destination("ABCD2345", "Methods: a/b", "R/Methods: a/b", "ABCD2345", "R"))
    'ABCD2345 Methods- a-b'
    """
    return f"{destination.key} {_UNSAFE.sub("-", destination.name)}".strip()


def stage(plan: ChangePlan, folder: Path) -> int:
    """
    Copy the file of each import into the sub-folder of its destination and verify each copy.

    Parameters
    ----------
    plan : ChangePlan
        Plan whose imports are staged.
    folder : Path
        Staging folder; created when absent, refused when not empty. Each destination with
        imports receives the sub-folder named by `subfolder`.

    Returns
    -------
    int
        Number of files staged.

    Raises
    ------
    PlanError
        If the folder is not empty, a source file is missing, or a copy differs from the content
        recorded in the plan.
    """
    if folder.exists() and any(folder.iterdir()):
        raise PlanError(f"staging folder {folder} is not empty; empty it or choose another")
    folder.mkdir(parents=True, exist_ok=True)
    for op in plan.imports:
        source = Path(op.file.path)
        if not source.is_file():
            raise PlanError(f"source file of {op.work_id} not found: {source}")
        target = folder / subfolder(plan.destination(op.destination)) / op.staged_name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        if digest_file(target).sha256 != op.file.sha256:
            raise PlanError(f"staged copy {target} differs from the content in the plan")
    return len(plan.imports)
