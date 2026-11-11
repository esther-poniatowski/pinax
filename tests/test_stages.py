"""End-to-end test of the stages on a synthetic library snapshot, and of the command line."""

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner
import yaml

from conftest import (
    SourceTree,
    Storage,
    api_collection,
    api_item,
    md5_of,
    pdf_attachment,
    pdf_bytes,
)
from fake_zotero import FakeZotero
from pinax import stages
from pinax.cli import EXIT_ERROR, EXIT_LIBRARY, app
from pinax.config import load_config
from pinax.errors import LibraryError
from pinax.library.client import ZoteroClient
from pinax.library.connector import Connector

TITLE = "Temporal dynamics of attention in a recurrent network model"
URL = "http://127.0.0.1:23119"
NEW_TITLE = "Learning dynamics of deep linear networks under spectral bias"


def _snapshot(directory: Path, items: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    collections = [
        api_collection("REVIEW01", "review"),
        api_collection("BACKGR01", "bg", "REVIEW01"),
    ]
    (directory / "items.json").write_text(json.dumps(items), encoding="utf-8")
    (directory / "collections.json").write_text(json.dumps(collections), encoding="utf-8")


def test_stages_from_inventory_to_export(
    tmp_path: Path, sources: SourceTree, storage: Storage
) -> None:
    sources.add("refs/2004_Smith_temporal_dynamics.pdf", pdf_bytes("old"), [f"{TITLE}. Abstract."])
    new = sources.add("refs/2020_Roe_learning.pdf", pdf_bytes("new"), [f"{NEW_TITLE}. Abstract."])
    config_path = tmp_path / "pinax.yml"
    config_path.write_text(
        f"workspace: ws\nsources: {{root: {sources.root}}}\n"
        "targets: [{folder: refs, destination: {path: review/bg}, scope: {key: REVIEW01}}]\n"
        f"library: {{storage: {storage.root}}}\n",
        encoding="utf-8",
    )
    config = load_config(config_path, tmp_path)
    before = [
        api_item("OLDITEM1", title=TITLE, date="2004", creators=["Smith"], citationKey="smith2004")
    ]
    _snapshot(config.workspace / "library" / "current", before)

    assert stages.make_inventory(config, sources.reader)["contents"] == 2
    assert stages.match(config, "current") == {"matched:name": 1, "absent:-": 1}
    plan = stages.make_plan(config, "current")
    assert [op.item for op in plan.attachments] == ["OLDITEM1"]
    assert [op.item for op in plan.filings] == ["OLDITEM1"]
    assert [op.staged_name for op in plan.imports] == ["2020_Roe_learning.pdf"]
    folder, count = stages.stage_imports(config)
    assert count == 1 and (folder / "BACKGR01 bg" / "2020_Roe_learning.pdf").is_file()
    assert "const ATTACH" in stages.write_script(config).read_text(encoding="utf-8")

    storage.store(
        "ATTOLD01",
        "Smith.pdf",
        (sources.root / "refs/2004_Smith_temporal_dynamics.pdf").read_bytes(),
    )
    storage.store("ATTNEW01", "Roe - 2020.pdf", new.read_bytes())
    after = before + [
        pdf_attachment("ATTOLD01", "OLDITEM1", "Smith.pdf"),
        api_item(
            "NEWITEM1",
            title=NEW_TITLE,
            date="2020",
            creators=["Roe"],
            collections=["BACKGR01"],
            publicationTitle="J",
            citationKey="roe2020",
        ),
        pdf_attachment("ATTNEW01", "NEWITEM1", "Roe - 2020.pdf", md5=md5_of(new.read_bytes())),
    ]
    after[0] = api_item(
        "OLDITEM1",
        title=TITLE,
        date="2004",
        creators=["Smith"],
        collections=["BACKGR01"],
        citationKey="smith2004",
    )
    _snapshot(config.workspace / "library" / "after", after)
    report = stages.check(config, "after", sources.reader, None)
    assert report.passed, report.to_json()

    stages.match(config, "after")
    routes, shared = stages.export(config, "after", [config.workspace / "plan.json"], None)
    assert routes == {"matched": 1, "imported": 1}
    assert not shared
    evidence = yaml.safe_load((config.workspace / "evidence.yml").read_text(encoding="utf-8"))
    imported = [e for e in evidence["files"] if e["route"] == "imported"]
    assert [(e["zotero_item"], e["citation_key"]) for e in imported] == [("NEWITEM1", "roe2020")]


def test_cli_reports_missing_artifacts_and_invalid_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["plan", "--config", str(tmp_path / "absent.yml")])
    assert result.exit_code == EXIT_ERROR
    assert "configuration file not found" in result.output
    config = tmp_path / "pinax.yml"
    config.write_text(
        "sources: {root: s}\ntargets: [{folder: ., destination: {key: D}}]\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["script", "--config", str(config)])
    assert result.exit_code == EXIT_ERROR
    assert "run `pinax plan` first" in result.output


def test_cli_exits_with_status_3_when_the_library_is_unreachable(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = tmp_path / "pinax.yml"
    config.write_text(
        "sources: {root: s}\ntargets: [{folder: ., destination: {key: D}}]\n"
        f"library: {{api: 'http://127.0.0.1:{port}'}}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["probe", "--config", str(config)])
    assert result.exit_code == EXIT_LIBRARY, result.output
    assert "cannot reach" in result.output


def test_cli_prints_the_configuration_merged_over_the_defaults(tmp_path: Path) -> None:
    config = tmp_path / "pinax.yml"
    config.write_text(
        "sources: {root: s}\ntargets: [{folder: ., destination: {key: D}}]\n"
        "matching: {title_words: 6}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["config", "--config", str(config)])
    assert result.exit_code == 0, result.output
    printed = yaml.safe_load(result.output)
    assert printed["matching"]["title_words"] == 6
    assert printed["matching"]["opening_words"] == 80
    assert printed["sources"]["pages"] == 2


RECORDS = """
@article{doe2001,
  title = {An Existing Synthetic Work},
  author = {Doe, Jane},
  year = {2001},
  doi = {10.5555/old}
}
@article{roe2020,
  title = {A Synthetic Work To Create},
  author = {Roe, Ann},
  journal = {Journal of Examples},
  year = {2020},
  doi = {10.5555/new}
}
"""


def _fake_snapshot(directory: Path, zotero: FakeZotero) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "items.json").write_text(json.dumps(zotero.items), encoding="utf-8")
    collections = json.dumps(zotero.collections())
    (directory / "collections.json").write_text(collections, encoding="utf-8")


def test_records_from_export_to_creation_check_and_evidence(
    tmp_path: Path, sources: SourceTree, storage: Storage
) -> None:
    sources.add("refs/refs.bib", RECORDS.encode())
    zotero = FakeZotero(
        items=[
            api_item(
                "OLDITEM1",
                title="An existing synthetic work",
                DOI="10.5555/old",
                collections=["BACKGR01"],
                citationKey="doe2001",
            )
        ]
    )
    config_path = tmp_path / "pinax.yml"
    config_path.write_text(
        f"workspace: ws\nsources: {{root: {sources.root}}}\n"
        "targets: [{folder: refs, destination: {path: review/background}}]\n"
        f"library: {{storage: {storage.root}}}\n",
        encoding="utf-8",
    )
    config = load_config(config_path, tmp_path)
    library_dir = config.workspace / "library"
    _fake_snapshot(library_dir / "current", zotero)

    assert stages.make_inventory(config, sources.reader)["records"] == 2
    counts = stages.match(config, "current")
    assert counts["records matched:doi"] == 1 and counts["records absent:-"] == 1
    plan = stages.make_plan(config, "current")
    assert [op.identity for op in plan.creations] == ["doi:10.5555/new"] and not plan.filings
    client, connector = ZoteroClient(URL, zotero.transport), Connector(URL, zotero.transport)
    results = stages.create(config, "current", client, connector, None)
    assert [(r.outcome.value, r.item) for r in results] == [("created", "NEW00001")]
    log = json.loads((config.workspace / "creation-log.json").read_text(encoding="utf-8"))
    assert log["connector"] == {"prefs": {"version": "test"}}
    assert [entry["item"] for entry in log["creations"]] == ["NEW00001"]

    _fake_snapshot(library_dir / "after", zotero)
    report = stages.check(config, "after", sources.reader, None)
    assert report.passed, report.to_json()
    stages.match(config, "after")
    routes, _ = stages.export(config, "after", [config.workspace / "plan.json"], None)
    assert routes == {"matched": 1, "created": 1}
    evidence = yaml.safe_load((config.workspace / "evidence.yml").read_text(encoding="utf-8"))
    assert [(e["key"], e["route"], e["citation_key"]) for e in evidence["records"]] == [
        ("doe2001", "matched", "doe2001"),
        ("roe2020", "created", "made1"),
    ]


def test_a_run_after_a_failure_waits_for_the_reconciliation(
    tmp_path: Path, sources: SourceTree, storage: Storage
) -> None:
    sources.add("refs/refs.bib", RECORDS.encode())
    zotero = FakeZotero(ignore_update=True)
    config_path = tmp_path / "pinax.yml"
    config_path.write_text(
        f"workspace: ws\nsources: {{root: {sources.root}}}\n"
        "targets: [{folder: refs, destination: {key: BACKGR01}}]\n"
        f"library: {{storage: {storage.root}}}\n",
        encoding="utf-8",
    )
    config = load_config(config_path, tmp_path)
    _fake_snapshot(config.workspace / "library" / "current", zotero)
    stages.make_inventory(config, sources.reader)
    stages.match(config, "current")
    assert len(stages.make_plan(config, "current").creations) == 2
    client, connector = ZoteroClient(URL, zotero.transport), Connector(URL, zotero.transport)
    first = stages.create(config, "current", client, connector, None, sleep=lambda _: None)
    assert [r.outcome.value for r in first] == ["failed"]
    with pytest.raises(LibraryError, match="ended failed on doi:10.5555/old"):
        stages.create(config, "current", client, connector, None)
    zotero.ignore_update = False
    second = stages.create(config, "current", client, connector, None, reconciled=True)
    assert [r.outcome.value for r in second] == ["exists", "created"]
