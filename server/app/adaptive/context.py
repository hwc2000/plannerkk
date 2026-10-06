"""The one boundary where shared schemas become the graph's ExecutionContext."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .state import ExecutionContext, ExecutionContextModel

ContextConverter = Callable[[object | None, Sequence[object]], Mapping[str, Any]]


def to_execution_context(
    profile: object | None,
    records: Sequence[object],
    *,
    converter: ContextConverter,
) -> ExecutionContext:
    """Convert pending shared schemas at one replaceable integration boundary.

    The converter is required on purpose: this module must not guess the final
    UserProfile/ExecutionRecord field names or nesting.  Once teammates publish
    those contracts, only their converter implementation should need to change;
    graph nodes continue to consume the normalized ExecutionContext.
    """
    value = ExecutionContextModel.model_validate(converter(profile, records))
    return value.model_dump()  # type: ignore[return-value]
