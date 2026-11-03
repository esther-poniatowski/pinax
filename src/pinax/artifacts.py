"""
Reading and writing of the JSON artifacts exchanged by the stages.

Functions
---------
write_json(path, data) -> None
    Write a JSON document atomically.
read_json(path) -> Any
    Read a JSON document, reporting a malformed file as an artifact error.
write_text(path, text) -> None
    Write a text artifact atomically.
"""

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from pinax.errors import ArtifactError


def write_text(path: Path, text: str) -> None:
    """
    Write a text artifact atomically.

    The text goes to a temporary file in the same directory, which then replaces the target, so an
    interrupted run never leaves a truncated artifact for the next stage.

    Parameters
    ----------
    path : Path
        Target file; its parent directories are created.
    text : str
        Content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_json(path: Path, data: Any) -> None:
    """
    Write a JSON document atomically.

    Parameters
    ----------
    path : Path
        Target file.
    data : Any
        JSON-serializable value.
    """
    write_text(path, json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n")


def read_json(path: Path) -> Any:
    """
    Read a JSON document, reporting a malformed file as an artifact error.

    Parameters
    ----------
    path : Path
        JSON file.

    Returns
    -------
    Any
        Decoded value.

    Raises
    ------
    ArtifactError
        If the file is missing or is not valid JSON.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ArtifactError(f"artifact not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ArtifactError(f"malformed JSON in {path}: {error}") from error
