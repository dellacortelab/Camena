"""The companion: a small tamagotchi whose state lives on the server.

Stats decay with wall-clock time and are recomputed on every read, so nothing
has to tick in the background. Talking to it feeds it; showing it things with
the camera is its favourite snack; it sleeps at night in the owner's timezone.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .db import DB, iso, utcnow

KEY = "pet"

# XP thresholds for each life stage. A normal day of use is roughly 10-20 XP.
STAGES = [("egg", 0), ("sprout", 5), ("nymph", 40), ("muse", 200)]

EXPRESSIONS = {
    "happy", "excited", "curious", "thinking", "proud", "sleepy",
    "sad", "worried", "surprised", "love", "neutral", "silly",
}

HUNGER_PER_HOUR = 4.0      # 0 = full, 100 = starving
ENERGY_PER_HOUR = 3.0      # drains while awake, refills while asleep
SLEEP_HOURS = (23, 7)      # local time, [start, end)


def _default() -> dict:
    now = iso(utcnow())
    return {
        "name": "Cam",
        "xp": 0,
        "hunger": 20.0,
        "energy": 80.0,
        "affection": 50.0,
        "expression": "neutral",
        "thought": "",
        "updated_at": now,
        "born_at": now,
    }


def stage_for(xp: int) -> str:
    current = STAGES[0][0]
    for name, threshold in STAGES:
        if xp >= threshold:
            current = name
    return current


def next_stage_xp(xp: int) -> int | None:
    for _, threshold in STAGES:
        if xp < threshold:
            return threshold
    return None


def is_night(now: datetime, tz: ZoneInfo) -> bool:
    hour = now.astimezone(tz).hour
    start, end = SLEEP_HOURS
    return hour >= start or hour < end


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _advance(state: dict, now: datetime, tz: ZoneInfo) -> dict:
    last = datetime.fromisoformat(state["updated_at"])
    hours = max(0.0, (now - last).total_seconds() / 3600)
    asleep = is_night(now, tz)
    state["hunger"] = _clamp(state["hunger"] + HUNGER_PER_HOUR * hours * (0.4 if asleep else 1.0))
    state["energy"] = _clamp(state["energy"] + (ENERGY_PER_HOUR * 2 if asleep else -ENERGY_PER_HOUR) * hours)
    # Affection slowly fades if it's ignored for more than a day.
    if hours > 24:
        state["affection"] = _clamp(state["affection"] - (hours - 24) * 0.5)
    state["updated_at"] = iso(now)
    return state


def view(state: dict, now: datetime, tz: ZoneInfo) -> dict:
    """What the frontend renders: raw stats plus derived stage and status."""
    asleep = is_night(now, tz)
    if state["hunger"] > 80:
        status = "hungry"
    elif state["energy"] < 15 or asleep:
        status = "sleepy"
    elif state["affection"] < 25:
        status = "lonely"
    else:
        status = "ok"
    return {
        **state,
        "stage": stage_for(state["xp"]),
        "next_stage_xp": next_stage_xp(state["xp"]),
        "asleep": asleep,
        "status": status,
    }


class Pet:
    def __init__(self, db: DB, tz: ZoneInfo):
        self.db = db
        self.tz = tz

    def _load(self) -> dict:
        state = self.db.get_json(KEY) or _default()
        return _advance(state, utcnow(), self.tz)

    def _save(self, state: dict) -> dict:
        self.db.set_json(KEY, state)
        return view(state, utcnow(), self.tz)

    def get(self) -> dict:
        return self._save(self._load())

    def interact(self, kind: str) -> dict:
        """Called by the app on every exchange. kind: 'chat' | 'voice' | 'photo' | 'pet'."""
        state = self._load()
        gains = {"chat": (1, 12, 2), "voice": (2, 12, 3), "photo": (2, 20, 3), "pet": (0, 0, 6)}
        xp, food, love = gains.get(kind, (1, 8, 1))
        stage_before = stage_for(state["xp"])
        state["xp"] += xp
        state["hunger"] = _clamp(state["hunger"] - food)
        state["affection"] = _clamp(state["affection"] + love)
        state["energy"] = _clamp(state["energy"] + 2)
        view_ = self._save(state)
        view_["evolved"] = stage_for(state["xp"]) != stage_before
        return view_

    def express(self, expression: str, thought: str = "") -> dict:
        state = self._load()
        state["expression"] = expression if expression in EXPRESSIONS else "neutral"
        state["thought"] = thought[:80]
        return self._save(state)

    def rename(self, name: str) -> dict:
        state = self._load()
        state["name"] = name.strip()[:24] or state["name"]
        return self._save(state)

    def prompt_summary(self) -> str:
        v = self.get()
        return (
            f"Your companion body is named {v['name']}, currently a {v['stage']} "
            f"(xp {v['xp']}), hunger {v['hunger']:.0f}/100, energy {v['energy']:.0f}/100, "
            f"affection {v['affection']:.0f}/100, status '{v['status']}'."
        )
