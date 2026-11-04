"""End-to-end test of the stages on a synthetic library snapshot, and of the command line."""

import json
from pathlib import Path
from typing import Any

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
from pinax import stages
from pinax.cli import EXIT_ERROR, app
from pinax.config import load_config

TITLE = "Temporal dynamics of attention in a recurrent network model"
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
    config = load_config(config_path)
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
    evidence = (config.workspace / "evidence.tsv").read_text(encoding="utf-8")
    assert "\timported\tNEWITEM1\troe2020" in evidence


def test_cli_reports_missing_artifacts_and_invalid_configs(tmp_path: Path) -> None:
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
