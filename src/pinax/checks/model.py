"""
Results of the checks of a plan against the library.

Classes
-------
Outcome
    Outcome of one check.
CheckResult
    Outcome of the check of one operation.
Report
    Results of every check of a plan.
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    """
    Outcome of one check.

    `PASS`: the operation holds. `NOTE`: it holds, with a fact the researcher should read, such as
    an incomplete record. `FAIL`: it does not hold.
    """

    PASS = "pass"
    NOTE = "note"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    """
    Outcome of the check of one operation.

    Attributes
    ----------
    operation : str
        Kind of operation: `import`, `attach`, `file`, `correct` or `log`.
    target : str
        Item key or work identity.
    outcome : Outcome
        Outcome.
    detail : str
        Evidence of the outcome.
    """

    operation: str
    target: str
    outcome: Outcome
    detail: str = ""


@dataclass
class Report:
    """
    Results of every check of a plan.

    Attributes
    ----------
    results : list[CheckResult]
        Results in plan order.
    """

    results: list[CheckResult] = field(default_factory=list)

    def add(self, operation: str, target: str, outcome: Outcome, detail: str = "") -> None:
        """Record one result."""
        self.results.append(CheckResult(operation, target, outcome, detail))

    def extend(self, results: list[CheckResult]) -> None:
        """Record several results."""
        self.results.extend(results)

    def count(self, outcome: Outcome) -> int:
        """Number of results with an outcome."""
        return sum(result.outcome is outcome for result in self.results)

    @property
    def passed(self) -> bool:
        """Whether no check failed."""
        return not self.count(Outcome.FAIL)

    def to_json(self) -> dict[str, Any]:
        """Serializable form of the report."""
        return {
            "summary": {outcome.value: self.count(outcome) for outcome in Outcome},
            "results": [
                {**asdict(result), "outcome": result.outcome.value} for result in self.results
            ],
        }
