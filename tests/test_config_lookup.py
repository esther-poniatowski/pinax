"""Tests of the resolution of the root of a reconciliation and of its configuration file.

The root is the folder given by `--root`, else by `PINAX_ROOT`, else the nearest folder, from the
current one upwards, holding `config/tools/pinax.yml` or `pinax.yml`, else the current folder.
Without `--config`, a command reads the one of both files that exists below the root, and both
existing is an error. A given `--config` is read from the current folder, and the relative paths
written in the file resolve against the root.
"""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pinax.cli import EXIT_ERROR, app
from pinax.config import find_root, locate_config
from pinax.errors import ConfigError

NESTED = Path("config/tools/pinax.yml")


def _config(title_words: int) -> str:
    """Valid configuration whose number of title words identifies the file read."""
    return (
        "sources: {root: s}\ntargets: [{folder: ., destination: {key: D}}]\n"
        f"matching: {{title_words: {title_words}}}\n"
    )


def _write(folder: Path, files: dict[Path | str, str]) -> Path:
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


def _title_words(*arguments: str, env: dict[str, str] | None = None) -> int:
    """Number of title words printed by `pinax config`, run in the current folder."""
    result = CliRunner().invoke(app, ["config", *arguments], env=env)
    assert result.exit_code == 0, result.output
    return yaml.safe_load(result.output)["matching"]["title_words"]


def test_lookup_reads_the_file_of_config_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, {NESTED: _config(7)})
    monkeypatch.chdir(tmp_path)
    assert locate_config(tmp_path) == tmp_path / NESTED
    assert _title_words() == 7


def test_lookup_reads_the_file_at_the_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, {"pinax.yml": _config(9)})
    monkeypatch.chdir(tmp_path)
    assert locate_config(tmp_path) == tmp_path / "pinax.yml"
    assert _title_words() == 9


def test_two_configuration_files_are_an_error_naming_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, {NESTED: _config(7), "pinax.yml": _config(9)})
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="two configuration files"):
        locate_config(tmp_path)
    result = CliRunner().invoke(app, ["plan"])
    assert result.exit_code == EXIT_ERROR
    assert str(tmp_path / NESTED) in result.output
    assert str(tmp_path / "pinax.yml") in result.output


def test_given_config_is_read_from_the_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, {NESTED: _config(7), "settings/other.yml": _config(9)})
    monkeypatch.chdir(tmp_path / "settings")
    assert locate_config(tmp_path, Path("other.yml")) == Path("other.yml")
    assert _title_words("-r", str(tmp_path), "-c", "other.yml") == 9


def test_given_absent_config_is_an_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["plan", "--config", str(tmp_path / "absent.yml")])
    assert result.exit_code == EXIT_ERROR
    assert "configuration file not found" in result.output


def test_missing_configuration_names_both_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="config/tools/pinax.yml or .*pinax.yml"):
        locate_config(tmp_path)
    result = CliRunner().invoke(app, ["plan"])
    assert result.exit_code == EXIT_ERROR
    assert "configuration file not found:" in result.output


def test_root_is_found_upwards_from_the_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write(tmp_path / "reconciliation", {NESTED: _config(7), "notes/deep/a.md": "# A\n"})
    assert find_root(root / "notes/deep") == root.resolve()
    assert find_root(tmp_path) == tmp_path.resolve()
    monkeypatch.chdir(root / "notes/deep")
    assert _title_words() == 7


def test_root_is_read_from_the_environment_below_the_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seven = _write(tmp_path / "seven", {"pinax.yml": _config(7)})
    nine = _write(tmp_path / "nine", {"pinax.yml": _config(9)})
    monkeypatch.chdir(tmp_path)
    assert _title_words(env={"PINAX_ROOT": str(seven)}) == 7
    assert _title_words("--root", str(nine), env={"PINAX_ROOT": str(seven)}) == 9


def test_paths_of_a_file_in_config_tools_resolve_against_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        {
            NESTED: "workspace: out\nsources: {root: refs}\n"
            "targets: [{folder: ., destination: {key: D}}]\n"
        },
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["script"])
    assert result.exit_code == EXIT_ERROR
    assert str(tmp_path.resolve() / "out" / "plan.json") in result.output


def test_absent_header_is_a_usage_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, {"pinax.yml": _config(7)})
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["export", "--header", "absent.txt"])
    assert result.exit_code == EXIT_ERROR
    assert "absent.txt" in result.output and "does not exist" in result.output
