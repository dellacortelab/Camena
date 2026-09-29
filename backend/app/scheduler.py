"""The heartbeat: fires due reminders and runs due proactive tasks.

Runs inside the API process every 30 seconds. Reminders never touch Claude.
Tasks run one at a time so a burst of schedules cannot stampede your plan's
usage limits.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from . import schedule as sched
from .db import iso, utcnow

log = logging.getLogger("camena.scheduler")
TICK_SECONDS = 30
NUDGE_AFTER = timedelta(hours=24)
NUDGE_HOURS = range(10, 20)  # local time; never at night


class Scheduler:
    def __init__(self, db, push, brain, settings, speech=None):
        self.speech = speech
        self.db = db
        self.push = push
        self.brain = brain
        self.settings = settings
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="camena-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the heartbeat must survive anything
                log.exception("scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)

    async def tick(self) -> None:
        now = iso(utcnow())
        for r in self.db.all(
            "SELECT id, text FROM reminders WHERE fired_at IS NULL AND cancelled = 0 AND due_at <= ? ORDER BY due_at",
            (now,),
        ):
            # Mark first so a crash mid-send cannot fire the same reminder twice.
            self.db.run("UPDATE reminders SET fired_at = ? WHERE id = ?", (now, r["id"]))
            self.db.add_inbox("reminder", "Reminder", r["text"])
            self.push.send("⏰ Reminder", r["text"])

        due = self.db.all(
            "SELECT * FROM tasks WHERE active = 1 AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at",
            (now,),
        )
        for task in due:
            await self.run_task(task)

        self.nudge()
        await self.brain.reap_idle()
        if self.speech is not None:
            await asyncio.to_thread(self.speech.unload_if_idle)

    def nudge(self, now: datetime | None = None) -> bool:
        """The tamagotchi move: after a day of silence the companion asks for you, once a day."""
        now = now or utcnow()
        local = now.astimezone(self.settings.timezone)
        if local.hour not in NUDGE_HOURS or self.db.get_json("last_nudge_date") == local.date().isoformat():
            return False
        last = self.db.one("SELECT created_at FROM messages WHERE role = 'user' ORDER BY id DESC LIMIT 1")
        if not last or now - datetime.fromisoformat(last["created_at"]) < NUDGE_AFTER:
            return False
        pet = self.brain.pet.get()
        body = {
            "hungry": f"{pet['name']} is hungry. Show it something interesting?",
            "lonely": f"{pet['name']} misses you.",
            "sleepy": f"{pet['name']} is dozing, but would wake up for you.",
        }.get(pet["status"], f"{pet['name']} wonders what you're up to today.")
        self.db.set_json("last_nudge_date", local.date().isoformat())
        self.push.send(pet["name"], body)
        return True

    async def run_task(self, task: dict) -> None:
        started = utcnow()
        # Advance the schedule before running: a slow or failing run must not be retried every tick.
        nxt = sched.next_run(task["schedule"], started, self.settings.timezone)
        self.db.run(
            "UPDATE tasks SET next_run_at = ?, last_run_at = ?, active = ? WHERE id = ?",
            (iso(nxt) if nxt else None, iso(started), 1 if nxt else 0, task["id"]),
        )
        try:
            result, notified = await asyncio.wait_for(
                self.brain.run_task(task["title"], task["prompt"]),
                timeout=self.settings.task_timeout_seconds,
            )
        except asyncio.TimeoutError:
            result, notified = "(timed out)", []
        except Exception as e:  # noqa: BLE001
            log.exception("task %s failed", task["id"])
            result, notified = f"(failed: {e})", []
        self.db.run("UPDATE tasks SET last_result = ? WHERE id = ?", (result[:4000], task["id"]))
        log.info("task %s '%s' ran; notified=%s", task["id"], task["title"], notified)
