"""
Configuration of one reconciliation, read from a YAML file.

One file declares the folder of sources, the destination collection of each of its folders, the
library, the parameters of the matching, and the files of resolutions and corrections. The file is
merged over the defaults shipped with the package, `defaults.yml`, from which every optional key
takes its default; a null default, as for `staging`, selects a fallback that the documentation of
the key states. Relative paths resolve against the directory of the configuration file, never
against the current directory; the folder of a target is relative to the root of the sources.

Classes
-------
RecordFiles
    Pattern of the names of record exports, and their format.
SourcesConfig
    Folder of reference files and the part of each PDF that is read.
CollectionRef
    Collection of the library, named by its key or by its path.
Target
    Folder of the sources and the collection that receives its items.
LibraryConfig
    Endpoints of the Zotero desktop application.
MatchingConfig
    Thresholds of the matching and of the confirmation by title.
Config
    Complete configuration.

Functions
---------
load_defaults() -> dict[str, Any]
    Defaults shipped with the package.
merge(base, override) -> dict[str, Any]
    Mapping of `base` overridden by `override`, merged key by key.
effective_data(path) -> dict[str, Any]
    Configuration file merged over the defaults, before validation.
load_config(path) -> Config
    Read and validate a configuration file.
"""

from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, get_origin

import yaml

from pinax.errors import ConfigError
from pinax.names import NameTemplate, compile_template
from pinax.records.readers import formats
from pinax.text import MIN_WORD_LENGTH, fold, words

DEFAULTS = "defaults.yml"
"""Package resource holding the default of every optional key."""


@dataclass(frozen=True)
class RecordFiles:
    """
    Pattern of the names of record exports, and their format.

    Attributes
    ----------
    pattern : str
        Shell pattern matched against a file name, ignoring case, such as `*.bib`.
    format : str
        Name of the reader of the files, such as `bibtex`.
    """

    pattern: str
    format: str


@dataclass(frozen=True)
class SourcesConfig:
    """
    Folder of reference files and the part of each PDF that is read.

    Attributes
    ----------
    root : Path
        Directory whose folders hold the files; the targets name folders relative to it.
    ignore : tuple[str, ...]
        File names skipped by the inventory.
    pages : int
        Number of opening pages whose text is extracted.
    names : tuple[NameTemplate, ...]
        Syntaxes of the file names, tried in order by the match by name.
    records : tuple[RecordFiles, ...]
        Patterns of the record exports, the first matching pattern deciding the format; a file
        that matches one is read as records, not as a reference file.
    """

    root: Path
    ignore: tuple[str, ...]
    pages: int
    names: tuple[NameTemplate, ...]
    records: tuple[RecordFiles, ...]


@dataclass(frozen=True)
class CollectionRef:
    """
    Collection of the library, named by its key or by its path.

    A path is resolved against the snapshot when the plan is built, so that a collection can be
    named as the researcher sees it.

    Attributes
    ----------
    key : str
        Eight-character key of the local API, empty when the path names the collection.
    path : str
        Names from the top level joined by `/`, such as `Review/Methods`, empty when the key names
        the collection.
    """

    key: str
    path: str

    def __str__(self) -> str:
        return f"key {self.key}" if self.key else f"path {self.path}"


@dataclass(frozen=True)
class Target:
    """
    Folder of the sources and the collection that receives its items.

    Attributes
    ----------
    folder : str
        Folder relative to the root of the sources, `.` for the root itself. A file belongs to the
        target with the longest folder that contains it.
    destination : CollectionRef
        Collection receiving the filed and imported items of the folder.
    scope : CollectionRef | None
        Collection whose sub-tree counts as filed; None for the destination.
    """

    folder: str
    destination: CollectionRef
    scope: CollectionRef | None

    def contains(self, folder: str) -> bool:
        """Whether a folder relative to the root lies in the folder of the target."""
        return self.folder == "." or folder == self.folder or folder.startswith(self.folder + "/")


@dataclass(frozen=True)
class LibraryConfig:
    """
    Endpoints of the Zotero desktop application.

    Attributes
    ----------
    api : str
        Base URL of the desktop application; only loopback hosts are accepted.
    storage : Path
        Storage directory holding one sub-directory per attachment key.
    """

    api: str
    storage: Path


@dataclass(frozen=True)
class MatchingConfig:  # pylint: disable=too-many-instance-attributes
    """
    Thresholds of the matching and of the confirmation by title.

    Attributes
    ----------
    title_words : int
        Opening title words that must appear in sequence to confirm a match. Fewer words let short
        generic titles confirm against unrelated pages.
    reject_below : float
        Share of title words found in the pages below which a candidate is rejected.
    name_threshold : float
        Lowest overlap between file-name words and title words for a match by name.
    year_tolerance : int
        Largest difference between the year of a file name and the year of an item.
    opening_words : int
        Window, in words from the start of the first page, in which a title must start for the
        reverse search to confirm it; a title found later is a citation.
    reverse_min_words : int
        Shortest title, in words, that the reverse search looks for.
    surname_prefix : int
        Shortest surname or file-name word compared by prefix, so that a garbled surname still
        matches; shorter words must be equal.
    undated_penalty : float
        Score removed from a match by name when the year cannot be compared, so that a dated
        match wins a tie.
    stop_words : frozenset[str]
        Words ignored by the overlap of a file name with a title, folded like the words compared.
    """

    title_words: int
    reject_below: float
    name_threshold: float
    year_tolerance: int
    opening_words: int
    reverse_min_words: int
    surname_prefix: int
    undated_penalty: float
    stop_words: frozenset[str]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "MatchingConfig":
        """
        Validated section `matching`, merged over the defaults.

        Parameters
        ----------
        data : dict[str, Any]
            Section holding every field of the class.

        Returns
        -------
        MatchingConfig
            Thresholds; each value takes the type of its field.

        Raises
        ------
        ConfigError
            If a key is unknown or missing, or a value has the wrong type.
        """
        known = {item.name for item in fields(cls)}
        _reject_unknown(data, known, "matching")
        missing = sorted(known - set(data))
        if missing:
            raise ConfigError(f"missing keys in matching: {", ".join(missing)}")
        values = {item.name: _typed(data[item.name], item.type, item.name) for item in fields(cls)}
        return cls(**values)


@dataclass(frozen=True)
class Config:  # pylint: disable=too-many-instance-attributes
    """
    Complete configuration.

    Attributes
    ----------
    workspace : Path
        Directory receiving the artifacts of every stage.
    sources : SourcesConfig
        Folder of reference files.
    targets : tuple[Target, ...]
        Folders of the sources and their collections, at least one.
    library : LibraryConfig
        Zotero endpoints.
    matching : MatchingConfig
        Matching thresholds.
    resolutions : Path | None
        YAML file of manual resolutions of matches.
    corrections : Path | None
        YAML file of corrections of item records.
    staging : Path | None
        Folder receiving the files to import; defaults to `staged/` in the workspace.
    """

    workspace: Path
    sources: SourcesConfig
    targets: tuple[Target, ...]
    library: LibraryConfig
    matching: MatchingConfig
    resolutions: Path | None
    corrections: Path | None
    staging: Path | None


def _mapping(value: Any, where: str) -> dict[str, Any]:
    """Mapping of a section, empty when the section is absent."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    return value


def _path(value: Any, base: Path, where: str) -> Path:
    """Absolute path of a value, resolved against the directory of the configuration file."""
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where} must be a non-empty path")
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _optional_path(value: Any, base: Path, where: str) -> Path | None:
    """Absolute path of a value, or None when the key is absent."""
    return None if value is None else _path(value, base, where)


def _strings(value: Any, where: str) -> tuple[str, ...]:
    """List of strings of a key, empty when the key is absent."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(value)


def _reject_unknown(data: dict[str, Any], known: set[str], where: str) -> None:
    """Fail on a key outside the known keys of a section."""
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"unknown keys in {where}: {", ".join(unknown)}")


def _typed(value: Any, expected: Any, name: str) -> Any:
    """Value of a field of `MatchingConfig` checked against its type; a list becomes a set."""
    where = f"matching.{name}"
    if get_origin(expected) is frozenset:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{where} must be a list of strings")
        ignored = [word for word in value if words(word) != [fold(word)]]
        if ignored:
            raise ConfigError(
                f"{where} holds {", ".join(ignored)}: a stop word is one word of at least "
                f"{MIN_WORD_LENGTH} letters or digits, since shorter words are always ignored"
            )
        return frozenset(fold(word) for word in value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be of type {expected.__name__}")
    if expected is int and not isinstance(value, int):
        raise ConfigError(f"{where} must be of type int")
    return expected(value)


def _sources(data: dict[str, Any], base: Path) -> SourcesConfig:
    """Validated section `sources`."""
    _reject_unknown(data, {"root", "ignore", "pages", "names", "records"}, "sources")
    pages = data.get("pages")
    if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
        raise ConfigError("sources.pages must be a positive integer")
    names = _strings(data.get("names"), "sources.names")
    if not names:
        raise ConfigError("sources.names must list at least one template")
    return SourcesConfig(
        root=_path(data.get("root"), base, "sources.root"),
        ignore=_strings(data.get("ignore"), "sources.ignore"),
        pages=pages,
        names=tuple(compile_template(text) for text in names),
        records=_record_files(data.get("records")),
    )


def _record_files(value: Any) -> tuple[RecordFiles, ...]:
    """Validated list `sources.records`; an empty list reads no file as records."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("sources.records must be a list of patterns and formats")
    known = set(formats())
    found = []
    for index, entry in enumerate(value):
        where = f"sources.records[{index}]"
        data = _mapping(entry, where)
        _reject_unknown(data, {"pattern", "format"}, where)
        pattern, name = data.get("pattern"), data.get("format")
        if not isinstance(pattern, str) or not pattern:
            raise ConfigError(f"{where}.pattern must be a non-empty pattern")
        if name not in known:
            raise ConfigError(f"{where}.format must be one of {", ".join(sorted(known))}")
        found.append(RecordFiles(pattern, str(name)))
    return tuple(found)


def _library(data: dict[str, Any], base: Path) -> LibraryConfig:
    """Validated section `library`."""
    _reject_unknown(data, {"api", "storage"}, "library")
    api = data.get("api")
    if not isinstance(api, str):
        raise ConfigError("library.api must be a URL")
    return LibraryConfig(
        api=api.rstrip("/"), storage=_path(data.get("storage"), base, "library.storage")
    )


def _collection(value: Any, where: str) -> CollectionRef:
    """Collection named by exactly one of the keys `key` and `path`."""
    data = _mapping(value, where)
    _reject_unknown(data, {"key", "path"}, where)
    named = [name for name in ("key", "path") if data.get(name)]
    if len(named) != 1 or not all(isinstance(data[name], str) for name in named):
        raise ConfigError(f"{where} must hold exactly one of `key` and `path`, as a string")
    key, path = str(data.get("key") or ""), str(data.get("path") or "").strip("/")
    return CollectionRef(key=key, path=path)


def _folder(value: Any, root: Path, where: str) -> str:
    """Folder relative to the root, `.` for the root; an absolute folder must lie under it."""
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where} must be a non-empty path")
    path = Path(value).expanduser()
    if path.is_absolute():
        if not path.is_relative_to(root):
            raise ConfigError(f"{where} lies outside sources.root: {value}")
        path = path.relative_to(root)
    folder = PurePosixPath(path.as_posix())
    if ".." in folder.parts:
        raise ConfigError(f"{where} must not climb above sources.root: {value}")
    return str(folder)


def _targets(value: Any, root: Path) -> tuple[Target, ...]:
    """Validated list `targets`: at least one target, each folder named once."""
    if not isinstance(value, list) or not value:
        raise ConfigError("targets must list at least one folder and its destination")
    targets = []
    for index, entry in enumerate(value):
        where = f"targets[{index}]"
        data = _mapping(entry, where)
        _reject_unknown(data, {"folder", "destination", "scope"}, where)
        scope = data.get("scope")
        targets.append(
            Target(
                folder=_folder(data.get("folder"), root, f"{where}.folder"),
                destination=_collection(data.get("destination"), f"{where}.destination"),
                scope=None if scope is None else _collection(scope, f"{where}.scope"),
            )
        )
    folders = [target.folder for target in targets]
    repeated = sorted({folder for folder in folders if folders.count(folder) > 1})
    if repeated:
        raise ConfigError(f"folders named by several targets: {", ".join(repeated)}")
    return tuple(targets)


def load_defaults() -> dict[str, Any]:
    """
    Defaults shipped with the package.

    Returns
    -------
    dict[str, Any]
        Content of the resource `defaults.yml`: the default of every optional key.
    """
    text = resources.files("pinax").joinpath(DEFAULTS).read_text(encoding="utf-8")
    return _mapping(yaml.safe_load(text), DEFAULTS)


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Mapping of `base` overridden by `override`, merged key by key.

    Parameters
    ----------
    base : dict[str, Any]
        Defaults.
    override : dict[str, Any]
        Values of the consumer.

    Returns
    -------
    dict[str, Any]
        New mapping: two mappings under one key are merged recursively, and any other value of
        `override`, a list included, replaces the value of `base`.

    Examples
    --------
    >>> merge({"a": {"x": 1, "y": 2}, "b": [1]}, {"a": {"y": 3}, "b": [2]})
    {'a': {'x': 1, 'y': 3}, 'b': [2]}
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def effective_data(path: Path) -> dict[str, Any]:
    """
    Configuration file merged over the defaults, before validation.

    Parameters
    ----------
    path : Path
        YAML configuration file.

    Returns
    -------
    dict[str, Any]
        Merged mapping, with paths as written.

    Raises
    ------
    ConfigError
        If the file is missing or is not a YAML mapping.
    """
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    try:
        data = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    for section in ("sources", "library", "matching"):
        _mapping(data.get(section), section)
    return merge(load_defaults(), data)


def load_config(path: Path) -> Config:
    """
    Read and validate a configuration file.

    Parameters
    ----------
    path : Path
        YAML configuration file.

    Returns
    -------
    Config
        Validated configuration with absolute paths.

    Raises
    ------
    ConfigError
        If the file is missing, is not YAML, or holds an invalid or unknown key.
    """
    data = effective_data(path)
    base = path.resolve().parent
    known = {"workspace", "sources", "targets", "library", "matching"}
    known |= {"resolutions", "corrections", "staging"}
    _reject_unknown(data, known, str(path))
    sources = _sources(_mapping(data["sources"], "sources"), base)
    return Config(
        workspace=_path(data["workspace"], base, "workspace"),
        sources=sources,
        targets=_targets(data.get("targets"), sources.root),
        library=_library(_mapping(data["library"], "library"), base),
        matching=MatchingConfig.from_mapping(_mapping(data["matching"], "matching")),
        resolutions=_optional_path(data["resolutions"], base, "resolutions"),
        corrections=_optional_path(data["corrections"], base, "corrections"),
        staging=_optional_path(data["staging"], base, "staging"),
    )
