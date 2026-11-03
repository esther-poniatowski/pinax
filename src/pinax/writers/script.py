"""
Assembly of the Zotero script from its units.

Classes
-------
ScriptGenerator
    Renders a plan into one script by concatenating the fragments of its units.

Functions
---------
default_units() -> list[ScriptUnit]
    Units of the default script, in order.
"""

from collections.abc import Sequence

from pinax.plans.model import ChangePlan
from pinax.writers.units import (
    AttachUnit,
    ContextUnit,
    CorrectUnit,
    FileUnit,
    HeaderUnit,
    LogUnit,
    PreflightUnit,
    ResultUnit,
    ScriptUnit,
)


def default_units() -> list[ScriptUnit]:
    """
    Units of the default script, in order.

    The preflight precedes every write unit, and the result unit closes the script.

    Returns
    -------
    list[ScriptUnit]
        Header, context, log, preflight, attach, file, correct, result.
    """
    return [
        HeaderUnit(),
        ContextUnit(),
        LogUnit(),
        PreflightUnit(),
        AttachUnit(),
        FileUnit(),
        CorrectUnit(),
        ResultUnit(),
    ]


class ScriptGenerator:
    """
    Renders a plan into one script by concatenating the fragments of its units.

    Parameters
    ----------
    units : Sequence[ScriptUnit] | None
        Units in script order; None for `default_units()`.
    """

    def __init__(self, units: Sequence[ScriptUnit] | None = None) -> None:
        self._units = list(units) if units is not None else default_units()

    def render(self, plan: ChangePlan) -> str:
        """
        Render the script of a plan.

        Parameters
        ----------
        plan : ChangePlan
            Plan to apply.

        Returns
        -------
        str
            Script text; fragments are separated by blank lines.
        """
        fragments = [unit.render(plan) for unit in self._units]
        return "\n".join(fragment for fragment in fragments if fragment)
