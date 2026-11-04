"""
Resolution of the targets of a configuration against a library snapshot.

A target names its collections by key or by path. The plan records keys, so each path is resolved
once, when the plan is built, and a path that names no collection or several stops the plan: the
plan never creates a collection and never guesses between two.

Classes
-------
TargetMap
    Destination of each folder of the sources.
"""

from collections.abc import Sequence
from pathlib import PurePosixPath

from pinax.config import CollectionRef, Target
from pinax.errors import PlanError
from pinax.library.model import Library
from pinax.plans.model import Destination


class TargetMap:
    """
    Destination of each folder of the sources.

    Parameters
    ----------
    library : Library
        Library snapshot taken before the change.
    targets : Sequence[Target]
        Targets of the configuration.

    Raises
    ------
    PlanError
        If a collection is missing or ambiguous, or one destination is given two scopes.
    """

    def __init__(self, library: Library, targets: Sequence[Target]) -> None:
        self._library = library
        self._targets: list[tuple[Target, Destination]] = []
        by_key: dict[str, Destination] = {}
        for target in targets:
            key = self._resolve(target.destination)
            scope = self._resolve(target.scope) if target.scope is not None else key
            destination = Destination(
                key=key,
                name=library.collections[key].name,
                path=library.collection_path(key),
                scope=scope,
                scope_path=library.collection_path(scope),
            )
            known = by_key.setdefault(key, destination)
            if known.scope != scope:
                raise PlanError(
                    f"destination {destination.path} is given two scopes, "
                    f"{known.scope_path} and {destination.scope_path}"
                )
            self._targets.append((target, destination))
        self.destinations = tuple(by_key.values())

    def _resolve(self, ref: CollectionRef) -> str:
        """Key of a collection named by key or by path."""
        if ref.key:
            if ref.key not in self._library.collections:
                raise PlanError(
                    f"collection {ref.key} is not in the library; create it in Zotero first"
                )
            return ref.key
        keys = sorted(
            key
            for key in self._library.collections
            if self._library.collection_path(key) == ref.path
        )
        if not keys:
            raise PlanError(f"no collection has the path {ref.path}; create it in Zotero first")
        if len(keys) > 1:
            raise PlanError(
                f"several collections have the path {ref.path} ({", ".join(keys)}); "
                "name the destination by key"
            )
        return keys[0]

    def destination(self, folder: str) -> Destination:
        """
        Destination of a folder of the sources.

        Parameters
        ----------
        folder : str
            Folder relative to the root of the sources.

        Returns
        -------
        Destination
            Destination of the deepest target folder that contains the folder.

        Raises
        ------
        PlanError
            If no target contains the folder, which happens when the inventory predates a change
            of the targets.
        """
        holding = [(target, dest) for target, dest in self._targets if target.contains(folder)]
        if not holding:
            raise PlanError(f"no target contains the folder {folder}; run `pinax inventory` again")
        _, destination = max(holding, key=lambda pair: len(PurePosixPath(pair[0].folder).parts))
        return destination
