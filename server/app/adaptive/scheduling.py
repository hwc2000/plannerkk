"""Rule-based time placement for the reschedule strategy.

Pure functions over free windows: no storage, no LLM.  Free time is never left
unused just because a task does not fit a window whole: the remaining work is
split across windows in time order.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

Window = tuple[datetime, datetime]


def parse_windows(raw: Sequence[Sequence[str]]) -> list[Window]:
    return [(datetime.fromisoformat(start), datetime.fromisoformat(end)) for start, end in raw]


def minutes_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def fill(
    minutes: int,
    windows: Sequence[Window],
    *,
    min_piece: int,
    max_piece: int | None,
    gap: int,
) -> tuple[list[Window], int]:
    """Place ``minutes`` of work into the earliest free time.

    Pieces are at least ``min_piece`` long and at most ``max_piece`` (one focus
    session for time_blocks users).  ``gap`` minutes separate pieces that share
    a window.  A remainder shorter than ``min_piece`` is never left behind.
    Returns the placements and the minutes that did not fit.
    """
    placements: list[Window] = []
    left = minutes
    for start, end in windows:
        cursor = start
        while left > 0:
            piece = min(left, minutes_between(cursor, end))
            if max_piece is not None:
                piece = min(piece, max_piece)
            rest = left - piece
            if 0 < rest < min_piece:
                piece -= min_piece - rest  # leave a workable remainder instead of a sliver
            if piece < min_piece:
                break
            placements.append((cursor, cursor + timedelta(minutes=piece)))
            left -= piece
            cursor += timedelta(minutes=piece + gap)
        if left == 0:
            break
    return placements, left


def pack(minutes_list: Sequence[int], windows: Sequence[Window], *, gap: int) -> list[Window] | None:
    """Place whole tasks in order, each inside one window; None if they do not fit."""
    placements: list[Window] = []
    index = 0
    cursor = windows[0][0] if windows else None
    for minutes in minutes_list:
        while index < len(windows):
            if cursor + timedelta(minutes=minutes) <= windows[index][1]:
                placements.append((cursor, cursor + timedelta(minutes=minutes)))
                cursor += timedelta(minutes=minutes + gap)
                break
            index += 1
            if index < len(windows):
                cursor = windows[index][0]
        else:
            return None
    return placements


def longest_window(windows: Sequence[Window]) -> int:
    return max((minutes_between(start, end) for start, end in windows), default=0)
