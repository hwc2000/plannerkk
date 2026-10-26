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
    gap: int,
) -> tuple[list[Window], int]:
    """Move ``minutes`` of the same work into free time: whole, cut only when no window holds it.

    Moving is time routing, so it never re-cuts the work: the work goes whole
    into the earliest window that holds it, even when it is longer than one
    focus session.  Cutting work by its content is the shrink's job, after a
    failure.  Only when no window holds it is it spread over what is free in
    time order, with no piece under half of it (nor ``min_piece``).  ``gap``
    minutes separate pieces that share a window.  Returns the placements and
    the minutes that did not fit.
    """
    whole = pack([minutes], windows, gap=gap)
    if whole is not None:
        return whole, 0
    shortest = min(minutes, max(min_piece, minutes // 2))
    placements, left = _spread(minutes, windows, shortest=shortest, cap=None, gap=gap, keep_whole_tail=False)
    if left == 0 and len(placements) > 1 and minutes_between(*placements[-1]) < shortest:
        # Everything fit but the last piece is a sliver: give it a workable share instead.
        placements, left = _spread(minutes, windows, shortest=shortest, cap=None, gap=gap, keep_whole_tail=True)
    return placements, left


def room_for(minutes: int, windows: Sequence[Window], *, min_piece: int, max_piece: int | None, gap: int) -> int:
    """Minutes of the work that every free slot of at least ``min_piece`` could take.

    For cutting work to a deadline: there the scope is rewritten into tasks that
    each fit a slot, so a short slot is a task of its own, not a sliver.
    """
    _, left = _spread(minutes, windows, shortest=min(minutes, min_piece), cap=max_piece, gap=gap, keep_whole_tail=False)
    return minutes - left


def _spread(minutes: int, windows: Sequence[Window], *, shortest: int, cap: int | None, gap: int,
            keep_whole_tail: bool) -> tuple[list[Window], int]:
    placements: list[Window] = []
    left = minutes
    for start, end in windows:
        cursor = start
        while left > 0:
            piece = min(left, minutes_between(cursor, end))
            if cap is not None:
                piece = min(piece, cap)
            rest = left - piece
            if keep_whole_tail and 0 < rest < shortest:
                piece -= shortest - rest  # leave a workable remainder instead of a sliver
            if piece < min(left, shortest):
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
