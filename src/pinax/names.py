"""
File-name templates: the syntaxes in which a consumer names its reference files.

A template describes the stem of a file name, without its extension, by three placeholders:
`{year}`, `{authors}` and `{title}`. The text between two placeholders is matched literally, so it
separates the parts of the name. A placeholder other than `{year}` matches any text, as short as
the rest of the template allows. Several templates may be declared; the first template that
matches the whole stem parses the name.

Classes
-------
NameTemplate
    One compiled template.
ParsedName
    Year, authors and title read from a file name.

Functions
---------
compile_template(text) -> NameTemplate
    Compile the text of a template.
parse_name(templates, name) -> ParsedName | None
    Parse a file name by the first template that matches its stem.

Examples
--------
>>> templates = [compile_template("{authors} - {year} - {title}"), compile_template("{title}")]
>>> parse_name(templates, "Doe and Roe - 2004 - A model of signals.pdf")
ParsedName(year=2004, authors='Doe and Roe', title='A model of signals')
>>> parse_name(templates, "notes on signals.pdf")
ParsedName(year=None, authors=None, title='notes on signals')
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
import re

from pinax.errors import ConfigError

PLACEHOLDERS = {
    "year": r"(?P<year>(?:1[5-9]|20)\d\d)[a-z]?",
    "authors": r"(?P<authors>.+?)",
    "title": r"(?P<title>.+?)",
}
"""Pattern of each placeholder; a year may carry one letter, as in `2004a`."""

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


@dataclass(frozen=True)
class NameTemplate:
    """
    One compiled template.

    Attributes
    ----------
    text : str
        Template as written in the configuration, such as `{year}_{title}`.
    pattern : re.Pattern[str]
        Expression matching a whole stem.
    """

    text: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class ParsedName:
    """
    Year, authors and title read from a file name.

    Attributes
    ----------
    year : int | None
        Year of the name, None when the template has no `{year}`.
    authors : str | None
        Text of the authors, None when the template has no `{authors}`: the matching then looks
        for the surnames among the words of the title.
    title : str
        Text of the title, or of the whole stem.
    """

    year: int | None
    authors: str | None
    title: str


def compile_template(text: str) -> NameTemplate:
    """
    Compile the text of a template.

    Parameters
    ----------
    text : str
        Template, such as `{year}_{title}`.

    Returns
    -------
    NameTemplate
        Template matching a whole stem.

    Raises
    ------
    ConfigError
        If a placeholder is unknown or repeated, or the template has no `{title}`.
    """
    parts: list[str] = []
    seen: list[str] = []
    end = 0
    for found in _PLACEHOLDER.finditer(text):
        name = found.group(1)
        if name not in PLACEHOLDERS:
            known = ", ".join(f"{{{key}}}" for key in PLACEHOLDERS)
            raise ConfigError(f"unknown placeholder {{{name}}} in `{text}`; known: {known}")
        if name in seen:
            raise ConfigError(f"placeholder {{{name}}} repeated in `{text}`")
        seen.append(name)
        parts += [re.escape(text[end : found.start()]), PLACEHOLDERS[name]]
        end = found.end()
    parts.append(re.escape(text[end:]))
    if "title" not in seen:
        raise ConfigError(f"template `{text}` has no {{title}}")
    return NameTemplate(text, re.compile("".join(parts)))


def parse_name(templates: Sequence[NameTemplate], name: str) -> ParsedName | None:
    """
    Parse a file name by the first template that matches its stem.

    Parameters
    ----------
    templates : Sequence[NameTemplate]
        Templates, in the order tried.
    name : str
        File name, with its extension.

    Returns
    -------
    ParsedName | None
        Parts of the name, or None when no template matches the whole stem.
    """
    stem = PurePath(name).stem
    for template in templates:
        found = template.pattern.fullmatch(stem)
        if found is None:
            continue
        parts = found.groupdict()
        year = parts.get("year")
        return ParsedName(int(year) if year else None, parts.get("authors"), parts["title"])
    return None
