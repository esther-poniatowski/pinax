"""
Configuration of one reconciliation, read from a YAML file.

One file declares the folder of sources, the library and its collections, the parameters of the
matching, and the files of resolutions and corrections. Relative paths resolve against the
directory of the configuration file, never against the current directory.

Classes
-------
SourcesConfig
    Folder of reference files and the part of each PDF that is read.
LibraryConfig
    Endpoints of the Zotero desktop application and the collections of the reconciliation.
MatchingConfig
    Thresholds of the matching and of the confirmation by title.
Config
    Complete configuration.

Functions
---------
load_config(path) -> Config
    Read and validate a configuration file.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pinax.errors import ConfigError

DEFAULT_API = "http://127.0.0.1:23119"
DEFAULT_STORAGE = "~/Zotero/storage"


@dataclass(frozen=True)
class SourcesConfig:
    """
    Folder of reference files and the part of each PDF that is read.

    Attributes
    ----------
    root : Path
        Directory whose sub-folders hold the files.
    folders : tuple[str, ...]
        Sub-folders to inventory, relative to `root`; empty for every file under `root`.
    ignore : tuple[str, ...]
        File names skipped by the inventory.
    pages : int
        Number of opening pages whose text is extracted.
    """

    root: Path
    folders: tuple[str, ...] = ()
    ignore: tuple[str, ...] = (".DS_Store",)
    pages: int = 2


@dataclass(frozen=True)
class LibraryConfig:
    """
    Endpoints of the Zotero desktop application and the collections of the reconciliation.

    Attributes
    ----------
    api : str
        Base URL of the desktop application; only loopback hosts are accepted.
    storage : Path
        Storage directory holding one sub-directory per attachment key.
    destination : str
        Key of the collection that receives filed and imported items.
    scope : str
        Key of the collection whose sub-tree counts as filed; defaults to `destination`.
    """

    destination: str
    api: str = DEFAULT_API
    storage: Path = Path(DEFAULT_STORAGE).expanduser()
    scope: str = ""

    @property
    def scope_key(self) -> str:
        """Key of the collection whose sub-tree counts as filed."""
        return self.scope or self.destination


@dataclass(frozen=True)
class MatchingConfig:
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
    """

    title_words: int = 8
    reject_below: float = 0.5
    name_threshold: float = 0.5
    year_tolerance: int = 1
    opening_words: int = 80
    reverse_min_words: int = 4


@dataclass(frozen=True)
class Config:
    """
    Complete configuration.

    Attributes
    ----------
    workspace : Path
        Directory receiving the artifacts of every stage.
    sources : SourcesConfig
        Folder of reference files.
    library : LibraryConfig
        Zotero endpoints and collections.
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
    library: LibraryConfig
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    resolutions: Path | None = None
    corrections: Path | None = None
    staging: Path | None = None


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    return value


def _path(value: Any, base: Path, where: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where} must be a non-empty path")
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _optional_path(value: Any, base: Path, where: str) -> Path | None:
    return None if value is None else _path(value, base, where)


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(value)


def _reject_unknown(data: dict[str, Any], known: set[str], where: str) -> None:
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"unknown keys in {where}: {", ".join(unknown)}")


def _sources(data: dict[str, Any], base: Path) -> SourcesConfig:
    _reject_unknown(data, {"root", "folders", "ignore", "pages"}, "sources")
    pages = data.get("pages", 2)
    if not isinstance(pages, int) or pages < 1:
        raise ConfigError("sources.pages must be a positive integer")
    ignore = _strings(data["ignore"], "sources.ignore") if "ignore" in data else (".DS_Store",)
    return SourcesConfig(
        root=_path(data.get("root"), base, "sources.root"),
        folders=_strings(data.get("folders"), "sources.folders"),
        ignore=ignore,
        pages=pages,
    )


def _library(data: dict[str, Any], base: Path) -> LibraryConfig:
    _reject_unknown(data, {"api", "storage", "destination", "scope"}, "library")
    destination = data.get("destination")
    if not isinstance(destination, str) or not destination:
        raise ConfigError("library.destination must be a collection key")
    scope = data.get("scope", "")
    if not isinstance(scope, str):
        raise ConfigError("library.scope must be a collection key")
    api = data.get("api", DEFAULT_API)
    if not isinstance(api, str):
        raise ConfigError("library.api must be a URL")
    return LibraryConfig(
        destination=destination,
        api=api.rstrip("/"),
        storage=_path(data.get("storage", DEFAULT_STORAGE), base, "library.storage"),
        scope=scope,
    )


def _matching(data: dict[str, Any]) -> MatchingConfig:
    defaults = MatchingConfig()
    known = set(defaults.__dataclass_fields__)
    _reject_unknown(data, known, "matching")
    values: dict[str, Any] = {}
    for name in known:
        if name not in data:
            continue
        expected = type(getattr(defaults, name))
        value = data[name]
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, expected) or isinstance(value, bool):
            raise ConfigError(f"matching.{name} must be of type {expected.__name__}")
        values[name] = value
    return MatchingConfig(**values)


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
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    try:
        data = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    base = path.resolve().parent
    known = {"workspace", "sources", "library", "matching", "resolutions", "corrections", "staging"}
    _reject_unknown(data, known, str(path))
    for section in ("sources", "library"):
        if section not in data:
            raise ConfigError(f"missing section `{section}` in {path}")
    return Config(
        workspace=_path(data.get("workspace", ".pinax"), base, "workspace"),
        sources=_sources(_mapping(data["sources"], "sources"), base),
        library=_library(_mapping(data["library"], "library"), base),
        matching=_matching(_mapping(data.get("matching"), "matching")),
        resolutions=_optional_path(data.get("resolutions"), base, "resolutions"),
        corrections=_optional_path(data.get("corrections"), base, "corrections"),
        staging=_optional_path(data.get("staging"), base, "staging"),
    )
