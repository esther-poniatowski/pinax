"""
Markdown worklist of a plan, for the review and the manual steps.

Functions
---------
render_worklist(plan, staging) -> str
    Render the steps and the operations of a plan.
"""

from pathlib import Path
import shlex
import urllib.parse

from pinax.plans.model import ChangePlan
from pinax.plans.staging import subfolder

EMPTY = "—"
"""Content of an empty table cell."""


def _cell(text: str) -> str:
    """Text escaped for a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _fields(fields: dict[str, str]) -> str:
    """Fields as `name=value` pairs."""
    return ", ".join(f"{name}={value}" for name, value in fields.items())


def _link(path: str) -> str:
    """Markdown link to a local file, named by the file name."""
    return f"[{_cell(Path(path).name)}](file://{urllib.parse.quote(path)})"


def render_worklist(plan: ChangePlan, staging: Path) -> str:
    """
    Render the steps and the operations of a plan.

    Parameters
    ----------
    plan : ChangePlan
        Plan to render.
    staging : Path
        Staging folder named in the import step.

    Returns
    -------
    str
        Markdown document: the ordered steps, then one table per kind of operation.
    """
    path = {dest.key: dest.path for dest in plan.destinations}
    lines = [
        "# Worklist of the change plan",
        "",
        "## Destinations",
        "",
        "| Collection | Key | Counted as filed under | Staged sub-folder |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{_cell(dest.path)}` | `{dest.key}` | `{_cell(dest.scope_path)}` | "
        f"{_cell(subfolder(dest))} |"
        for dest in plan.destinations
    ]
    lines += [
        "",
        "## Steps",
        "",
        "1. Review the tables below and the generated script.",
        f"2. Open the staging folder with `open {shlex.quote(str(staging))}`. For each sub-folder, "
        "select its collection in Zotero, then drag the files of the sub-folder, not the folder, "
        "into the collection.",
        '3. Run the script in Tools > Developer > Run JavaScript, with "Run as async function" '
        "ticked, and save the log it returns.",
        "4. Take a new snapshot and run `pinax check`.",
        "",
        f"## Import ({len(plan.imports)})",
        "",
        "| Staged name | Destination | DOI | Source |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {_cell(op.staged_name)} | `{_cell(path[op.destination])}` | {op.doi or EMPTY} | "
        f"{_link(op.file.path)} |"
        for op in plan.imports
    ]
    later = [op for op in plan.imports if op.also]
    if later:
        lines += [
            "",
            "The next plan files these imported works into the other destinations of their "
            "folders: "
            + "; ".join(
                f"{_cell(op.staged_name)} into "
                + ", ".join(f"`{_cell(path[key])}`" for key in op.also)
                for op in later
            )
            + ".",
        ]
    lines += [
        "",
        f"## Attach a PDF ({len(plan.attachments)})",
        "",
        "| Item | Citation key | Title | File |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{op.item}` | `{op.citation_key}` | {_cell(op.title)} | {_link(op.file.path)} |"
        for op in plan.attachments
    ]
    lines += [
        "",
        f"## File into a destination ({len(plan.filings)})",
        "",
        "| Item | Citation key | Title | Destination | Current collections |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{op.item}` | `{op.citation_key}` | {_cell(op.title)} | "
        f"`{_cell(path[op.destination])}` | {_cell("; ".join(op.current)) or EMPTY} |"
        for op in plan.filings
    ]
    lines += [
        "",
        f"## Correct a record ({len(plan.corrections)})",
        "",
        "| Item | Type | Fields | Note |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{op.item}` | {op.item_type or EMPTY} | {_cell(_fields(op.fields)) or EMPTY} | "
        f"{_cell(op.note)} |"
        for op in plan.corrections
    ]
    if plan.skipped:
        lines += [
            "",
            f"## Not imported ({len(plan.skipped)})",
            "",
            "| Work | Reason | Files |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| `{op.work_id}` | {_cell(op.reason)} | {_cell("; ".join(op.files))} |"
            for op in plan.skipped
        ]
    return "\n".join(lines) + "\n"
