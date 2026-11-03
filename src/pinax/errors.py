"""
Exceptions raised by the `pinax` package.

Classes
-------
PinaxError
    Base class of every error that the command line reports without a traceback.
ConfigError
    Invalid or missing configuration.
LibraryError
    Failed or refused access to the Zotero library.
ArtifactError
    Missing or malformed artifact of an earlier stage.
PlanError
    Change plan that cannot be built or staged.
"""


class PinaxError(Exception):
    """Base class of every error that the command line reports without a traceback."""


class ConfigError(PinaxError):
    """Invalid or missing configuration."""


class LibraryError(PinaxError):
    """Failed or refused access to the Zotero library."""


class ArtifactError(PinaxError):
    """Missing or malformed artifact of an earlier stage."""


class PlanError(PinaxError):
    """Change plan that cannot be built or staged."""
