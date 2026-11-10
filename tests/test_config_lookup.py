"""Tests of the lookup of the configuration file below the current directory."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pinax.cli import EXIT_ERROR, app
from pinax.config import locate_config
from pinax.errors import ConfigError

NESTED = Path("config/tools/pinax.yml")


def _config(title_words: int) -> str:
    """Valid configuration whose number of title words identifies the file read."""
    return (
        "sources: {root: s}\ntargets: [{folder: ., destination: {key: D}}]\n"
        f"matching: {{title_words: {title_words}}}\n"
    )


def _write(folder: Path, files: dict[Path | str, str]) -> None:
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _title_words(*arguments: str) -> int:
    """Number of title words printed by `pinax config`, run in the current directory."""
    result = CliRunner().invoke(app, ["config", *arguments])
    assert result.exit_code == 0, result.output
    return yaml.safe_load(result.output)["matching"]["title_words"]


def test_lookup_prefers_the_file_of_config_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, {NESTED: _config(7), "pinax.yml": _config(9)})
    monkeypatch.chdir(tmp_path)
    assert locate_config(None) == NESTED
    assert _title_words() == 7


def test_lookup_falls_back_on_the_file_of_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, {"pinax.yml": _config(9)})
    monkeypatch.chdir(tmp_path)
    assert locate_config(None) == Path("pinax.yml")
    assert _title_words() == 9


def test_given_config_is_read_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, {NESTED: _config(7), "pinax.yml": _config(9)})
    monkeypatch.chdir(tmp_path)
    assert locate_config(Path("pinax.yml")) == Path("pinax.yml")
    assert _title_words("--config", "pinax.yml") == 9


def test_missing_configuration_names_both_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="config/tools/pinax.yml or pinax.yml"):
        locate_config(None)
    result = CliRunner().invoke(app, ["plan"])
    assert result.exit_code == EXIT_ERROR
    assert "configuration file not found: config/tools/pinax.yml or pinax.yml" in result.output
