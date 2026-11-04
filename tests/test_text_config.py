"""Tests of the normalization of texts and of the configuration."""

from pathlib import Path

import pytest

from pinax.config import MatchingConfig, load_config, load_defaults
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
    assert content_words("The model of the signal", frozenset({"the", "of"})) == {
        "model",
        "signal",
    }


def test_title_head_keeps_opening_words() -> None:
    assert (
        title_head("A sparse model of the example signal in time", 4) == "sparse model the example"
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
        "workspace: out\nsources: {root: refs}\n"
        "targets:\n"
        "  - {folder: a, destination: {key: DEST0001}}\n"
        f"  - {{folder: {tmp_path}/refs/b/c/, destination: {{path: /Review/B/}}, scope: {{key: R}}}}\n"
        "library: {storage: store}\nmatching: {reject_below: 1}\n",
    )
    config = load_config(path)
    assert config.workspace == tmp_path / "out"
    assert config.sources.root == tmp_path / "refs"
    assert config.library.storage == tmp_path / "store"
    assert [(t.folder, str(t.destination), str(t.scope)) for t in config.targets] == [
        ("a", "key DEST0001", "None"),
        ("b/c", "path Review/B", "key R"),
    ]
    assert config.matching.reject_below == 1.0


TARGET = "targets: [{folder: ., destination: {key: D}}]\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("sources: {root: r}\n", "targets must list at least one folder"),
        ("sources: {root: r}\ntargets: []\n", "targets must list at least one folder"),
        ("sources: {root: r}\n" + TARGET + "extra: 1\n", "unknown keys"),
        (TARGET, "sources.root"),
        ("sources: {root: r, pages: 0}\n" + TARGET, "sources.pages"),
        ("sources: {root: r, folders: [a]}\n" + TARGET, "unknown keys in sources: folders"),
        ("sources: {root: r}\nlibrary: {destination: D}\n" + TARGET, "unknown keys in library"),
        (
            "sources: {root: r}\ntargets: [{folder: a, destination: {key: D, path: x}}]\n",
            "exactly one of `key` and `path`",
        ),
        ("sources: {root: r}\ntargets: [{folder: a, destination: {}}]\n", "exactly one"),
        ("sources: {root: r}\ntargets: [{folder: /elsewhere, destination: {key: D}}]\n", "outside"),
        ("sources: {root: r}\ntargets: [{folder: ../up, destination: {key: D}}]\n", "climb"),
        (
            "sources: {root: r}\n"
            "targets: [{folder: a, destination: {key: D}}, {folder: a/, destination: {key: E}}]\n",
            "folders named by several targets: a",
        ),
        ("sources: {root: r, names: []}\n" + TARGET, "sources.names must list"),
        ("sources: {root: r, names: ['{year}']}\n" + TARGET, "has no {title}"),
        ("sources: {root: r}\n" + TARGET + "matching: {title_words: x}\n", "title_words"),
        (
            "sources: {root: r}\n" + TARGET + "matching: {stop_words: the}\n",
            "matching.stop_words must be a list",
        ),
        ("sources: {root: r}\n" + TARGET + "matching: [1]\n", "must be a mapping"),
    ],
)
def test_config_rejects_invalid_files(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(_write(tmp_path / "pinax.yml", text))


def test_defaults_set_every_matching_key() -> None:
    config = MatchingConfig.from_mapping(load_defaults()["matching"])
    assert config.title_words == 8
    assert "the" in config.stop_words


def test_consumer_overrides_one_key_and_replaces_lists(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pinax.yml",
        "sources: {root: refs, ignore: [Thumbs.db]}\n"
        + TARGET
        + "matching: {stop_words: [Über, de, la], surname_prefix: 6}\n",
    )
    config = load_config(path)
    assert config.sources.ignore == ("Thumbs.db",)
    assert config.sources.pages == 2
    assert config.matching.stop_words == frozenset({"uber", "de", "la"})
    assert config.matching.surname_prefix == 6
    assert config.matching.title_words == 8
