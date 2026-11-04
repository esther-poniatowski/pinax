"""
Command-line interface for the `pinax` package.

Defines one command per stage, available via `python -m pinax` or `pinax` once installed. Every
command reads the configuration file given by `--config`.

Commands
--------
info : Display diagnostic information.
config : Print the configuration in effect, merged over the shipped defaults.
probe : Record the versions of the local API and the connector.
read : Save a snapshot of the library.
keys : Compare the citation keys of a snapshot with Better BibTeX.
inventory : Inventory the folder of sources.
match : Match each content with a snapshot.
plan : Build the change plan and its worklist.
stage : Stage the files to import.
script : Generate the Zotero script of the plan.
check : Check the plan against a snapshot taken after the change.
export : Write the evidence table and the reference list of each folder.

See Also
--------
typer.Typer
    Library for building CLI applications: https://typer.tiangolo.com/
"""

from collections import Counter
import json
from pathlib import Path
import subprocess  # nosec B404
from typing import Annotated

import typer
import yaml

from pinax import __version__, info, stages
from pinax.checks.model import Outcome
from pinax.config import Config, effective_data, load_config
from pinax.errors import PinaxError
from pinax.library.client import ZoteroClient
from pinax.sources.pdf import PopplerReader

app = typer.Typer(add_completion=False, no_args_is_help=True)

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Configuration file of the reconciliation.")
]
LabelOption = Annotated[
    str, typer.Option("--snapshot", "-s", help="Label of the library snapshot.")
]
EXIT_ERROR = 2
NONE = "-"
"""Placeholder printed for an absent value."""
EXIT_FAILED_CHECKS = 1


def _load(path: Path) -> Config:
    """Load a configuration, exiting with an error message when it is invalid."""
    try:
        return load_config(path)
    except PinaxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error


def _fail(error: PinaxError) -> typer.Exit:
    """Print an error and return the exit that the command raises."""
    typer.echo(f"error: {error}", err=True)
    return typer.Exit(EXIT_ERROR)


def _counts(counter: Counter[str]) -> str:
    """Counts of a counter as `key value` pairs, sorted by key."""
    return ", ".join(f"{key} {value}" for key, value in sorted(counter.items()))


@app.command("info")
def cli_info() -> None:
    """Display version and platform diagnostics."""
    typer.echo(info())


@app.command("config")
def cli_config(config: ConfigOption = Path("pinax.yml")) -> None:
    """Print the configuration in effect: the file merged over the shipped defaults."""
    _load(config)
    try:
        data = effective_data(config)
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), nl=False)


@app.command("probe")
def cli_probe(config: ConfigOption = Path("pinax.yml")) -> None:
    """Record the versions of the local API and the connector, without writing."""
    settings = _load(config)
    try:
        typer.echo(json.dumps(stages.probe(ZoteroClient(settings.library.api)), indent=1))
    except PinaxError as error:
        raise _fail(error) from error


@app.command("read")
def cli_read(config: ConfigOption = Path("pinax.yml"), snapshot: LabelOption = "current") -> None:
    """Save a snapshot of the library through the local API, without writing."""
    settings = _load(config)
    try:
        counts = stages.read_library(settings, ZoteroClient(settings.library.api), snapshot)
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(
        f"snapshot `{snapshot}`: {counts["collections"]} collections, {counts["items"]} items"
    )


@app.command("keys")
def cli_keys(config: ConfigOption = Path("pinax.yml"), snapshot: LabelOption = "current") -> None:
    """Compare the citation keys of a snapshot with those of Better BibTeX."""
    settings = _load(config)
    try:
        differences = stages.compare_keys(settings, ZoteroClient(settings.library.api), snapshot)
    except PinaxError as error:
        raise _fail(error) from error
    for key, (recorded, current) in sorted(differences.items()):
        typer.echo("\t".join([key, recorded or NONE, current or NONE]))
    typer.echo(f"{len(differences)} items whose key differs from Better BibTeX")


@app.command("inventory")
def cli_inventory(config: ConfigOption = Path("pinax.yml")) -> None:
    """Inventory the folder of sources: digests, DOI and text of the first pages."""
    settings = _load(config)
    try:
        counts = stages.make_inventory(settings, PopplerReader())
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(f"inventory: {_counts(counts)}")


@app.command("match")
def cli_match(config: ConfigOption = Path("pinax.yml"), snapshot: LabelOption = "current") -> None:
    """Match each content of the inventory with a snapshot of the library."""
    settings = _load(config)
    try:
        counts = stages.match(settings, snapshot)
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(f"matches (status:method): {_counts(counts)}")


@app.command("plan")
def cli_plan(config: ConfigOption = Path("pinax.yml"), snapshot: LabelOption = "current") -> None:
    """Build the change plan and its worklist; refuses while a match awaits a check."""
    settings = _load(config)
    try:
        plan = stages.make_plan(settings, snapshot)
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(
        f"plan: {len(plan.imports)} imports, {len(plan.attachments)} attachments, "
        f"{len(plan.filings)} filings, {len(plan.corrections)} corrections, "
        f"{len(plan.skipped)} skipped works"
    )


@app.command("stage")
def cli_stage(
    config: ConfigOption = Path("pinax.yml"),
    reveal: Annotated[bool, typer.Option("--open", help="Open the folder in Finder.")] = False,
) -> None:
    """Copy the file of each import into a staging folder that holds only them."""
    settings = _load(config)
    try:
        folder, count = stages.stage_imports(settings)
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(f"staged {count} files in {folder}")
    if reveal:
        subprocess.run(["open", str(folder)], check=False)  # nosec B603 B607


@app.command("script")
def cli_script(config: ConfigOption = Path("pinax.yml")) -> None:
    """Generate the Zotero script that applies the plan."""
    settings = _load(config)
    try:
        path = stages.write_script(settings)
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(f"script written to {path}")


@app.command("check")
def cli_check(
    config: ConfigOption = Path("pinax.yml"),
    snapshot: LabelOption = "after",
    log: Annotated[
        Path | None, typer.Option("--log", help="Action log returned by the script.")
    ] = None,
) -> None:
    """Check every operation of the plan against a snapshot taken after the change."""
    settings = _load(config)
    try:
        report = stages.check(settings, snapshot, PopplerReader(), log)
    except PinaxError as error:
        raise _fail(error) from error
    for result in report.results:
        if result.outcome is not Outcome.PASS:
            fields = [result.outcome.value.upper(), result.operation, result.target, result.detail]
            typer.echo("\t".join(fields))
    summary = ", ".join(f"{o.value} {report.count(o)}" for o in Outcome)
    typer.echo(f"checks: {summary}")
    if not report.passed:
        raise typer.Exit(EXIT_FAILED_CHECKS)


@app.command("export")
def cli_export(
    config: ConfigOption = Path("pinax.yml"),
    snapshot: LabelOption = "current",
    plan: Annotated[
        list[Path] | None, typer.Option("--plan", help="Applied plan defining imported files.")
    ] = None,
    header: Annotated[
        Path | None, typer.Option("--header", help="Comment block of the reference list.")
    ] = None,
) -> None:
    """Write the evidence table and the reference list of each folder."""
    settings = _load(config)
    try:
        routes, shared = stages.export(settings, snapshot, plan or [], header)
    except PinaxError as error:
        raise _fail(error) from error
    typer.echo(f"routes: {_counts(routes)}")
    for key, items in sorted(shared.items()):
        typer.echo(f"citation key {key} is carried by {", ".join(items)}")


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", "-v", help="Show the package version and exit."
    )
) -> None:
    """Reconcile a folder of reference files with a Zotero library."""
    if version:
        typer.echo(__version__)
        raise typer.Exit()
