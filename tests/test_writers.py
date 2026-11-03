"""
Tests of the generated Zotero script, executed against a mock of the Zotero object model.

The mock, `zotero_mock.js`, implements the calls that the script uses, drops the fields that a type
lacks on a type change, and runs the script several times on the same state, as a researcher
running it twice would. The tests are skipped where Node.js is not installed.
"""

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from pinax.plans.model import (
    AttachOp,
    ChangePlan,
    CorrectOp,
    CreatorSpec,
    Destination,
    FileOp,
    FileRef,
)
from pinax.writers.script import ScriptGenerator

NODE = shutil.which("node")
MOCK = Path(__file__).with_name("zotero_mock.js")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

FILE = "/synthetic/source/paper.pdf"
DESTINATION = Destination("DEST0001", "background", "review/background")


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "collections": {"DEST0001": {"id": 7, "name": "background"}},
        "items": {
            "ATTACH01": {"itemType": "journalArticle", "fields": {"title": "T1"}},
            "FILE0001": {"itemType": "journalArticle", "fields": {"title": "T2"}},
            "CHAPTER1": {
                "itemType": "journalArticle",
                "fields": {"title": "T3", "DOI": "10.5555/c", "publicationTitle": "A Book"},
            },
        },
        "files": [FILE],
    }
    state.update(overrides)
    return state


def _plan(**overrides: Any) -> ChangePlan:
    fields: dict[str, Any] = {
        "destination": DESTINATION,
        "scope": "DEST0001",
        "attachments": (AttachOp("ATTACH01", "k1", "T1", FileRef(FILE, "0" * 64, "0" * 32, 1)),),
        "filings": (FileOp("FILE0001", "k2", "T2"),),
        "corrections": (
            CorrectOp(
                "CHAPTER1",
                item_type="bookSection",
                fields={"date": "2001"},
                creators=(CreatorSpec("Doe", "Jane"), CreatorSpec("Some Institute")),
                carry={"publicationTitle": "bookTitle"},
                preserve=("DOI",),
            ),
        ),
    }
    fields.update(overrides)
    return ChangePlan(**fields)


def _run(tmp_path: Path, plan: ChangePlan, state: dict[str, Any], runs: int = 2) -> dict[str, Any]:
    script = tmp_path / "script.js"
    script.write_text(ScriptGenerator().render(plan), encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    assert NODE is not None
    result = subprocess.run(
        [NODE, str(MOCK), str(state_file), str(script), str(runs)],
        capture_output=True,
        text=True,
        check=True,
    )
    output: dict[str, Any] = json.loads(result.stdout)
    return output


def _outcomes(run: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(e["op"], e["item"], e["outcome"]) for e in run["log"]]


def test_script_applies_the_plan_then_skips_on_a_second_run(tmp_path: Path) -> None:
    result = _run(tmp_path, _plan(), _state())
    first, second = result["runs"]
    assert _outcomes(first) == [
        ("preflight", "", "done"),
        ("attach", "ATTACH01", "done"),
        ("file", "FILE0001", "done"),
        ("correct", "CHAPTER1", "done"),
    ]
    assert ("attach", "ATTACH01", "skip") in _outcomes(second)
    assert ("file", "FILE0001", "skip") in _outcomes(second)
    items = result["state"]
    assert items["ATTACH01"]["attachments"] == ["NEWATT01"]
    assert items["FILE0001"]["collections"] == [7]
    chapter = items["CHAPTER1"]
    assert chapter["itemType"] == "bookSection"
    assert chapter["fields"]["bookTitle"] == "A Book"
    assert chapter["fields"]["extra"] == "DOI: 10.5555/c"
    assert chapter["fields"]["date"] == "2001"
    assert chapter["creators"] == [
        {"firstName": "Jane", "lastName": "Doe", "creatorType": "author"},
        {"name": "Some Institute", "creatorType": "author"},
    ]


@pytest.mark.parametrize(
    ("state", "plan", "message"),
    [
        (_state(collections={"DEST0001": {"id": 7, "name": "renamed"}}), _plan(), "destination"),
        (_state(files=[]), _plan(), "files not found"),
        (
            _state(
                items={
                    **_state()["items"],
                    "FILE0001": {"itemType": "journalArticle", "deleted": 1},
                }
            ),
            _plan(),
            "in the trash: FILE0001",
        ),
        (
            _state(),
            _plan(corrections=(CorrectOp("CHAPTER1", item_type="thesis", fields={"DOI": "x"}),)),
            "invalid for their type: CHAPTER1: DOI",
        ),
    ],
)
def test_preflight_stops_before_any_write(
    tmp_path: Path, state: dict[str, Any], plan: ChangePlan, message: str
) -> None:
    result = _run(tmp_path, plan, state, runs=1)
    assert message in result["runs"][0]["error"]
    assert result["state"]["ATTACH01"]["attachments"] == []
    assert result["state"]["CHAPTER1"]["itemType"] == "journalArticle"


def test_units_without_operations_render_nothing() -> None:
    script = ScriptGenerator().render(_plan(attachments=(), filings=(), corrections=()))
    assert "ATTACH" not in script and "const FILE" not in script and "CORRECT" not in script
    assert script.index("preflight") < script.index("return JSON.stringify(log")
