"""Boundaries the graph talks through: the injected generator and the store.

The graph never imports a concrete store or LLM client.  Today an adapter can wrap the local
SQLite ``ExecutionStore``; after the move to the shared DB, a Supabase adapter
implements the same method and the graph does not change.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class PlanConflictError(Exception):
    """The plan changed after the draft was made (stale ``base_revision``)."""


class GenerationUnavailableError(Exception):
    """The generator cannot run at all (missing key, auth, quota); do not retry."""


class PlanValidationError(ValueError):
    """The generated plan broke a rule; another attempt with these errors may pass."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class PlanWriter(Protocol):
    def apply_recovery(
        self,
        *,
        user_id: str | None,
        project_id: str | None,
        base_revision: int,
        task_id: str,
        strategy: str,
        draft: Mapping[str, Any],
    ) -> None:
        """Replace ``task_id`` with the approved draft and record the approved
        ``strategy`` on the check-in that led to it, atomically.

        Must raise ``PlanConflictError`` instead of writing when the stored
        plan revision is no longer ``base_revision``.
        """
        ...
