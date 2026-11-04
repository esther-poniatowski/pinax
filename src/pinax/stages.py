"""
Stages of a reconciliation, each reading the artifacts of earlier stages and writing its own.

The command line calls these functions and prints their summaries; the functions do no printing.

Functions
---------
probe(client) -> dict[str, Any]
    Record the versions of the local API and the connector.
read_library(config, client, label) -> dict[str, int]
    Save a snapshot of the library.
compare_keys(config, client, label) -> dict[str, tuple[str, str]]
    Compare the citation keys of a snapshot with those of Better BibTeX.
make_inventory(config, reader) -> Counter[str]
    Inventory the sources.
match(config, label) -> Counter[str]
    Match every content with a snapshot.
make_plan(config, label) -> ChangePlan
    Build the change plan and its worklist.
stage_imports(config) -> tuple[Path, int]
    Stage the files to import.
write_script(config) -> Path
    Generate the Zotero script of the plan.
create(config, label, client, connector, limit) -> list[Creation]
    Create the items of the plan through the connector.
check(config, label, reader, log) -> Report
    Check the plan against a snapshot taken after the change.
export(config, label, plans, header) -> tuple[Counter[str], dict[str, list[str]]]
    Write the evidence file and the reference lists.
"""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pinax.artifacts import read_json, write_json, write_text
from pinax.checks.model import Report
from pinax.checks.operations import PlanChecker, check_log, read_log
from pinax.config import Config
from pinax.errors import LibraryError
from pinax.exports.evidence import EvidenceBuilder, EvidenceRow, RecordRow, render_evidence
from pinax.exports.references import DEFAULT_HEADER, render_references, shared_keys
from pinax.library.client import ZoteroClient
from pinax.library.connector import Connector, Creation, CreationRun, numeric_targets
from pinax.library.snapshot import load_snapshot, take_snapshot
from pinax.library.storage import StorageIndex
from pinax.matching.confirm import TitleConfirmer
from pinax.matching.matcher import Matcher
from pinax.matching.model import matches_from_json, matches_to_json, record_matches_from_json
from pinax.matching.resolutions import load_resolutions
from pinax.plans.builder import PlanBuilder
from pinax.plans.corrections import load_corrections
from pinax.plans.model import ChangePlan
from pinax.plans.staging import stage
from pinax.plans.worklist import render_worklist
from pinax.records.matching import RecordMatcher
from pinax.records.works import group_records
from pinax.sources.inventory import Inventory, build_inventory
from pinax.sources.pdf import PdfReader
from pinax.workspace import Workspace
from pinax.writers.script import ScriptGenerator

NO_METHOD = "-"
"""Method shown for a content that no route matched."""


def _workspace(config: Config) -> Workspace:
    """Workspace of a configuration."""
    return Workspace(config.workspace)


def _inventory(workspace: Workspace) -> Inventory:
    """Inventory saved in a workspace."""
    return Inventory.from_json(read_json(workspace.require(workspace.inventory, "inventory")))


def _plan(path: Path) -> ChangePlan:
    """Plan saved at a path."""
    return ChangePlan.from_json(read_json(path))


def _staging(config: Config) -> Path:
    """Staging folder of a configuration: the configured one, else the one of the workspace."""
    return config.staging or _workspace(config).staged


def probe(client: ZoteroClient) -> dict[str, Any]:
    """Record the versions of the local API and the connector."""
    return client.probe()


def read_library(config: Config, client: ZoteroClient, label: str) -> dict[str, int]:
    """Save a snapshot of the library under a label; returns the counts read."""
    return take_snapshot(client, _workspace(config).snapshot(label))


def compare_keys(config: Config, client: ZoteroClient, label: str) -> dict[str, tuple[str, str]]:
    """
    Compare the citation keys of a snapshot with those of Better BibTeX.

    Returns
    -------
    dict[str, tuple[str, str]]
        Item key mapped to the key of the snapshot and the key of Better BibTeX, for each item
        where they differ.
    """
    workspace = _workspace(config)
    library = load_snapshot(workspace.require(workspace.snapshot(label), "read"))
    items = list(library.regular())
    keys = client.citation_keys([item.key for item in items])
    return {
        item.key: (item.citation_key, keys.get(item.key, ""))
        for item in items
        if item.citation_key != keys.get(item.key, "")
    }


def make_inventory(config: Config, reader: PdfReader) -> Counter[str]:
    """
    Inventory the sources.

    Returns
    -------
    Counter[str]
        Counts of files, contents, contents with a DOI, records, record works, and record works
        whose records disagree.
    """
    folders = [target.folder for target in config.targets]
    inventory = build_inventory(config.sources, folders, reader)
    write_json(_workspace(config).inventory, inventory.to_json())
    works = group_records(inventory.records)
    return Counter(
        files=len(inventory.files),
        contents=len(inventory.contents),
        with_doi=sum(1 for content in inventory if content.doi),
        records=len(inventory.records),
        record_works=len(works),
        disagreeing_works=sum(1 for work in works if work.disagreements),
    )


def match(config: Config, label: str) -> Counter[str]:
    """
    Match every content and every record work with a snapshot.

    Returns
    -------
    Counter[str]
        Count of each status and method, such as `matched:doi`; the counts of the record works
        carry the prefix `records `.
    """
    workspace = _workspace(config)
    library = load_snapshot(workspace.require(workspace.snapshot(label), "read"))
    inventory = _inventory(workspace)
    stored = StorageIndex(config.library.storage).by_sha256(c.size for c in inventory)
    resolutions = load_resolutions(config.resolutions, inventory)
    matcher = Matcher.build(library, stored, config.matching, config.sources.names, resolutions)
    matches = matcher.match_all(inventory)
    records = RecordMatcher(library, config.matching, resolutions).match_all(
        group_records(inventory.records)
    )
    write_json(workspace.matches, matches_to_json(matches, label, records))
    counts = Counter(
        f"{m.status.value}:{m.method.value if m.method else NO_METHOD}" for m in matches
    )
    counts.update(
        f"records {m.status.value}:{m.method.value if m.method else NO_METHOD}" for m in records
    )
    return counts


def make_plan(config: Config, label: str) -> ChangePlan:
    """Build the change plan and its worklist from the matches against a snapshot."""
    workspace = _workspace(config)
    library = load_snapshot(workspace.require(workspace.snapshot(label), "read"))
    inventory = _inventory(workspace)
    data = read_json(workspace.require(workspace.matches, "match"))
    builder = PlanBuilder(library, inventory, config.targets)
    plan = builder.build(
        matches_from_json(data),
        load_corrections(config.corrections),
        record_matches_from_json(data),
    )
    write_json(workspace.plan, plan.to_json())
    write_text(workspace.worklist, render_worklist(plan, _staging(config)))
    return plan


def stage_imports(config: Config) -> tuple[Path, int]:
    """Stage the files to import; returns the staging folder and the number of files."""
    workspace = _workspace(config)
    plan = _plan(workspace.require(workspace.plan, "plan"))
    folder = _staging(config)
    return folder, stage(plan, folder)


def write_script(config: Config) -> Path:
    """Generate the Zotero script of the plan; returns its path."""
    workspace = _workspace(config)
    plan = _plan(workspace.require(workspace.plan, "plan"))
    write_text(workspace.script, ScriptGenerator().render(plan))
    return workspace.script


def create(
    config: Config,
    label: str,
    client: ZoteroClient,
    connector: Connector,
    limit: int | None,
) -> list[Creation]:
    """
    Create the items of the plan through the connector, one item per session.

    The connector is probed, and its answer recorded in the log, before any write; its targets are
    read from the application and checked against the snapshot that the plan was built from. The
    log holds the probe and the results, and is written after each item.

    Returns
    -------
    list[Creation]
        One result per creation attempted; the run stops at the first failure or ambiguous outcome.
    """
    workspace = _workspace(config)
    plan = _plan(workspace.require(workspace.plan, "plan"))
    if not plan.creations:
        return []
    library = load_snapshot(workspace.require(workspace.snapshot(label), "read"))
    versions = connector.ping()
    if not isinstance(versions, dict):
        raise LibraryError(f"unexpected answer of the connector ping: {str(versions)[:120]}")
    targets = numeric_targets(connector.selected_collection(), library)
    run = CreationRun(client, connector, targets)

    def record(results: list[Creation]) -> None:
        log = {"connector": versions, "creations": [result.to_json() for result in results]}
        write_json(workspace.creation_log, log)

    record([])
    return run.run(plan.creations, limit, record)


def check(config: Config, label: str, reader: PdfReader, log: Path | None) -> Report:
    """Check the plan against a snapshot taken after the change, and the action log if given."""
    workspace = _workspace(config)
    plan = _plan(workspace.require(workspace.plan, "plan"))
    library = load_snapshot(workspace.require(workspace.snapshot(label), "read"))
    checker = PlanChecker(
        library,
        StorageIndex(config.library.storage),
        reader,
        TitleConfirmer(config.matching.title_words, config.matching.reject_below),
        pages=config.sources.pages,
    )
    report = checker.check(plan)
    if log is not None:
        report.extend(check_log(plan, read_log(log)))
    write_json(workspace.report, report.to_json())
    return report


def export(
    config: Config, label: str, plans: Sequence[Path], header: Path | None
) -> tuple[Counter[str], dict[str, list[str]]]:
    """
    Write the evidence file and the reference lists from the matches against a snapshot.

    Returns
    -------
    tuple[Counter[str], dict[str, list[str]]]
        Count of each route over the files and the records, and the citation keys carried by
        several items.
    """
    workspace = _workspace(config)
    library = load_snapshot(workspace.require(workspace.snapshot(label), "read"))
    inventory = _inventory(workspace)
    data = read_json(workspace.require(workspace.matches, "match"))
    builder = EvidenceBuilder(
        library, StorageIndex(config.library.storage), [_plan(path) for path in plans]
    )
    rows = builder.build(inventory, matches_from_json(data))
    records = builder.build_records(inventory, record_matches_from_json(data))
    write_text(workspace.evidence, render_evidence(rows, records))
    text = header.read_text(encoding="utf-8") if header else DEFAULT_HEADER
    every: list[EvidenceRow | RecordRow] = [*rows, *records]
    write_text(workspace.references, render_references(every, text))
    return Counter(row.route.value for row in every), shared_keys(every)
