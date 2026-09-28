"""A deliberately small schedule language for proactive tasks.

    once 2026-10-01T07:30          one shot, local time
    daily 07:30                    every day
    weekdays 08:00                 Mon-Fri
    weekly mon 09:00               one weekday
    every 30m | every 2h           fixed interval (minimum 15 minutes)

Times are in the owner's timezone; next_run() returns UTC.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MIN_INTERVAL = timedelta(minutes=15)


class ScheduleError(ValueError):
    pass


def _hhmm(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ScheduleError(f"bad time {text!r}, expected HH:MM")
    return int(m[1]), int(m[2])


def _next_at(after_local: datetime, hour: int, minute: int, allowed_days: set[int]) -> datetime:
    candidate = after_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after_local:
        candidate += timedelta(days=1)
    for _ in range(8):
        if candidate.weekday() in allowed_days:
            return candidate
        candidate += timedelta(days=1)
    raise ScheduleError("no matching day")  # unreachable with a non-empty day set


def validate(spec: str) -> str:
    """Normalise a spec or raise ScheduleError. Returns the canonical form."""
    spec = " ".join(spec.lower().split())
    next_run(spec, datetime.now(timezone.utc), ZoneInfo("UTC"), allow_past_once=True)
    return spec


def next_run(spec: str, after: datetime, tz: ZoneInfo, allow_past_once: bool = False) -> datetime | None:
    """Next UTC fire time strictly after `after`, or None if the schedule is finished."""
    parts = spec.lower().split()
    if not parts:
        raise ScheduleError("empty schedule")
    local = after.astimezone(tz)
    kind = parts[0]

    if kind == "once" and len(parts) == 2:
        try:
            when = datetime.fromisoformat(parts[1])
        except ValueError as e:
            raise ScheduleError(f"bad datetime {parts[1]!r}") from e
        when = when.replace(tzinfo=tz) if when.tzinfo is None else when
        if when <= after and not allow_past_once:
            return None
        return when.astimezone(timezone.utc)

    if kind == "daily" and len(parts) == 2:
        h, m = _hhmm(parts[1])
        return _next_at(local, h, m, set(range(7))).astimezone(timezone.utc)

    if kind == "weekdays" and len(parts) == 2:
        h, m = _hhmm(parts[1])
        return _next_at(local, h, m, set(range(5))).astimezone(timezone.utc)

    if kind == "weekly" and len(parts) == 3 and parts[1][:3] in DAYS:
        h, m = _hhmm(parts[2])
        return _next_at(local, h, m, {DAYS.index(parts[1][:3])}).astimezone(timezone.utc)

    if kind == "every" and len(parts) == 2:
        m = re.fullmatch(r"(\d+)([mh])", parts[1])
        if not m:
            raise ScheduleError(f"bad interval {parts[1]!r}, expected e.g. 30m or 2h")
        delta = timedelta(minutes=int(m[1])) if m[2] == "m" else timedelta(hours=int(m[1]))
        if delta < MIN_INTERVAL:
            raise ScheduleError("intervals shorter than 15m would burn your usage limits")
        return (after + delta).astimezone(timezone.utc)

    raise ScheduleError(
        f"unrecognised schedule {spec!r}; use 'once <ISO>', 'daily HH:MM', "
        "'weekdays HH:MM', 'weekly <day> HH:MM' or 'every <N>m|<N>h'"
    )
