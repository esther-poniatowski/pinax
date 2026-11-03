"""Tests of the normalization of texts and of the configuration."""

from pathlib import Path

import pytest

from pinax.config import load_config
from pinax.errors import ConfigError
from pinax.text import (
    content_words,
    find_doi,
    normalize_doi,
    sequence_position,
    title_head,
    words,
)


def test_words_fold_accents_and_drop_short_tokens() -> None:
    assert words("Évaluation d'un modèle: 2e éd.") == ["evaluation", "modele"]


def test_apostrophes_split_words_in_every_form() -> None:
    expected = ["the", "brain", "router"]
    assert words("The brain's router") == expected
    assert words("The brain\u2019s router") == expected
    assert words("The brain`s router") == expected


def test_content_words_drop_stop_words() -> None:
    assert content_words("The model of the blink") == {"model", "blink"}


def test_title_head_keeps_opening_words() -> None:
    assert (
        title_head("A sparse model of the example signal in time", 4)
        == "sparse model the example"
    )


def test_sequence_position_respects_word_boundaries() -> None:
    page = words("the restart model; a start model follows")
    assert sequence_position(page, "start model") == 3
    assert sequence_position(page, "") is None
    assert sequence_position(page, "model restart") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://doi.org/10.1000/ABC", "10.1000/abc"),
        ("doi: 10.1000/abc.", "10.1000/abc"),
        ("  10.1000/abc  ", "10.1000/abc"),
        ("", ""),
    ],
)
def test_normalize_doi(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


def test_find_doi_returns_first_doi() -> None:
    assert find_doi("see 10.1111/one, then 10.2222/two") == "10.1111/one"
    assert not find_doi("no identifier here")


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_config_resolves_relative_paths_against_its_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pinax.yml",
        "workspace: out\nsources: {root: refs, folders: [a]}\n"
        "library: {destination: DEST0001, storage: store}\nmatching: {reject_below: 1}\n",
    )
    config = load_config(path)
    assert config.workspace == tmp_path / "out"
    assert config.sources.root == tmp_path / "refs"
    assert config.library.storage == tmp_path / "store"
    assert config.library.scope_key == "DEST0001"
    assert config.matching.reject_below == 1.0


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("sources: {root: r}\nlibrary: {}\n", "library.destination"),
        ("sources: {root: r}\nlibrary: {destination: D}\nextra: 1\n", "unknown keys"),
        ("library: {destination: D}\n", "missing section `sources`"),
        ("sources: {root: r, pages: 0}\nlibrary: {destination: D}\n", "sources.pages"),
        (
            "sources: {root: r}\nlibrary: {destination: D}\nmatching: {title_words: x}\n",
            "title_words",
        ),
    ],
)
def test_config_rejects_invalid_files(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(_write(tmp_path / "pinax.yml", text))
