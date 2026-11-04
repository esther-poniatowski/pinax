"""
Grouping of records into works by identity, with the disagreements among the records of a work.

Several exports of one library describe the same works, so records sharing an identity form one
work. Those records must agree on their title and their year: a disagreement is recorded, never
merged away, and the matching leaves such a work to check.

Classes
-------
RecordWork
    Records describing one work.

Functions
---------
group_records(records) -> list[RecordWork]
    Group records into works by identity.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from pinax.records.model import Record


@dataclass(frozen=True)
class RecordWork:
    """
    Records describing one work.

    Attributes
    ----------
    identity : str
        Identity shared by the records.
    records : tuple[Record, ...]
        Records in inventory order.
    disagreements : tuple[str, ...]
        Descriptions of the titles or years on which the records disagree.
    """

    identity: str
    records: tuple[Record, ...]
    disagreements: tuple[str, ...] = ()

    @property
    def best(self) -> Record:
        """Record holding the most fields, the first one on a tie; a record with metadata wins."""
        return max(
            self.records,
            key=lambda record: (record.has_metadata, len(record.fields) + len(record.creators)),
        )

    @property
    def refs(self) -> tuple[str, ...]:
        """References of the records, in inventory order."""
        return tuple(record.ref for record in self.records)

    @property
    def folders(self) -> tuple[str, ...]:
        """Distinct folders of the export files, in inventory order."""
        return tuple(dict.fromkeys(record.folder for record in self.records))


def _disagreements(records: tuple[Record, ...]) -> tuple[str, ...]:
    """Titles and years on which the records holding metadata disagree."""
    described = [record for record in records if record.has_metadata]
    found = []
    titles = sorted({record.normalized_title for record in described})
    if len(titles) > 1:
        found.append("titles differ: " + " | ".join(titles))
    years = sorted({record.year for record in described if record.year is not None})
    if len(years) > 1:
        found.append("years differ: " + ", ".join(str(year) for year in years))
    return tuple(found)


def group_records(records: Iterable[Record]) -> list[RecordWork]:
    """
    Group records into works by identity.

    Parameters
    ----------
    records : Iterable[Record]
        Records of every export, in inventory order.

    Returns
    -------
    list[RecordWork]
        Works in the order of their first record. Two records sharing a key but not an identity
        stay in two works.
    """
    groups: dict[str, list[Record]] = {}
    for record in records:
        groups.setdefault(record.identity, []).append(record)
    return [
        RecordWork(identity, tuple(members), _disagreements(tuple(members)))
        for identity, members in groups.items()
    ]
