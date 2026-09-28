"""Camena's own tools, served to Claude as an in-process MCP server.

These are the pieces Muse sells as "memory", "proactive" and "keeps working
after you close the app": they are just small tables plus a scheduler.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import schedule as sched
from .db import DB, iso, utcnow
from .pet import EXPRESSIONS, Pet
from .push import Push

SERVER_NAME = "camena"


@dataclass
class TurnContext:
    """Per-run state the tools can see. One instance per agent session."""

    mode: str = "chat"                     # 'chat' | 'task'
    notified: list[str] = field(default_factory=list)
    expression: dict | None = None


def _ok(payload: Any) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "note"


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer"}


def build_server(db: DB, pet: Pet, push: Push, settings, ctx: TurnContext):
    tz = settings.timezone
    notes_dir = settings.workspace_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    def local(ts: str | None) -> str | None:
        return datetime.fromisoformat(ts).astimezone(tz).strftime("%a %b %d %H:%M") if ts else None

    # ---- memory ------------------------------------------------------------

    @tool("remember", "Store a durable fact about the owner (preference, person, plan, allergy...). "
          "Store one fact per call, phrased so it makes sense on its own months later.",
          _obj({"text": S, "topic": {**S, "description": "short tag, e.g. food, family, work"}}, ["text"]))
    async def remember(a):
        topic = (a.get("topic") or "general").lower()[:32]
        dup = db.one("SELECT id FROM memories WHERE lower(text) = lower(?)", (a["text"],))
        if dup:
            return _ok(f"already remembered as #{dup['id']}")
        mid = db.run("INSERT INTO memories(text, topic, created_at) VALUES(?,?,?)",
                     (a["text"].strip(), topic, iso(utcnow())))
        return _ok(f"remembered #{mid}")

    @tool("recall", "Search stored memories by keyword (empty query lists the most recent 50).",
          _obj({"query": S}, ["query"]))
    async def recall(a):
        q = a["query"].strip()
        rows = db.all(
            "SELECT id, topic, text FROM memories WHERE text LIKE ? OR topic LIKE ? ORDER BY id DESC LIMIT 50",
            (f"%{q}%", f"%{q}%"),
        )
        return _ok(rows or "nothing matches")

    @tool("forget", "Delete a stored memory by id when the owner asks you to forget it or it is wrong.",
          _obj({"memory_id": I}, ["memory_id"]))
    async def forget(a):
        n = db.run("DELETE FROM memories WHERE id = ?", (a["memory_id"],))
        return _ok("forgotten" if n else "no such memory")

    # ---- lists -------------------------------------------------------------

    @tool("list_add", "Add items to a named list (groceries, packing, todo, gift ideas...). Creates the list if needed.",
          _obj({"list_name": S, "items": {"type": "array", "items": S, "minItems": 1}}, ["list_name", "items"]))
    async def list_add(a):
        name = a["list_name"].strip().lower()
        now = iso(utcnow())
        for item in a["items"]:
            db.run("INSERT INTO list_items(list_name, text, created_at) VALUES(?,?,?)", (name, item.strip(), now))
        return _ok(f"added {len(a['items'])} to '{name}'")

    @tool("list_show", "Show a list's open items (or every list's names if list_name is empty).",
          _obj({"list_name": S}, ["list_name"]))
    async def list_show(a):
        name = a["list_name"].strip().lower()
        if not name:
            return _ok(db.all("SELECT list_name, SUM(done = 0) AS open FROM list_items GROUP BY list_name"))
        return _ok(db.all("SELECT id, text FROM list_items WHERE list_name = ? AND done = 0 ORDER BY id", (name,)))

    @tool("list_check", "Mark list items done by id.",
          _obj({"item_ids": {"type": "array", "items": I, "minItems": 1}}, ["item_ids"]))
    async def list_check(a):
        n = sum(db.run("UPDATE list_items SET done = 1 WHERE id = ?", (i,)) for i in a["item_ids"])
        return _ok(f"checked {n}")

    # ---- reminders -----------------------------------------------------------

    @tool("reminder_set", "Set a push-notification reminder. `when` is a local ISO datetime like 2026-10-01T07:30 "
          "(owner's timezone). Resolve relative times ('in 20 minutes') from the current time in your instructions.",
          _obj({"text": S, "when": S}, ["text", "when"]))
    async def reminder_set(a):
        try:
            when = datetime.fromisoformat(a["when"])
        except ValueError:
            return _err("`when` must be ISO like 2026-10-01T07:30")
        when = when.replace(tzinfo=tz) if when.tzinfo is None else when
        if when <= utcnow():
            return _err("that time is in the past")
        rid = db.run("INSERT INTO reminders(text, due_at, created_at) VALUES(?,?,?)",
                     (a["text"], iso(when), iso(utcnow())))
        return _ok(f"reminder #{rid} set for {local(iso(when))}")

    @tool("reminder_list", "List upcoming reminders.", _obj({}, []))
    async def reminder_list(a):
        rows = db.all("SELECT id, text, due_at FROM reminders WHERE fired_at IS NULL AND cancelled = 0 ORDER BY due_at")
        return _ok([{**r, "due_at": local(r["due_at"])} for r in rows] or "none")

    @tool("reminder_cancel", "Cancel a reminder by id.", _obj({"reminder_id": I}, ["reminder_id"]))
    async def reminder_cancel(a):
        n = db.run("UPDATE reminders SET cancelled = 1 WHERE id = ? AND fired_at IS NULL", (a["reminder_id"],))
        return _ok("cancelled" if n else "no such pending reminder")

    # ---- proactive tasks -----------------------------------------------------

    @tool("task_create",
          "Create a proactive background task: Camena runs `prompt` on `schedule` with web access, and the run "
          "notifies the owner only if it calls `notify`. Write the prompt so a fresh session can do it alone, "
          "including when to notify (e.g. 'notify only if the price drops below $300'). "
          "Schedules: 'once 2026-10-01T07:30', 'daily 07:30', 'weekdays 08:00', 'weekly mon 09:00', 'every 2h' (min 15m).",
          _obj({"title": S, "prompt": S, "schedule": S}, ["title", "prompt", "schedule"]))
    async def task_create(a):
        if ctx.mode == "task":
            return _err("background tasks cannot create more tasks")
        try:
            spec = sched.validate(a["schedule"])
            nxt = sched.next_run(spec, utcnow(), tz)
        except sched.ScheduleError as e:
            return _err(str(e))
        if nxt is None:
            return _err("that schedule never fires (time already passed?)")
        tid = db.run("INSERT INTO tasks(title, prompt, schedule, next_run_at, created_at) VALUES(?,?,?,?,?)",
                     (a["title"], a["prompt"], spec, iso(nxt), iso(utcnow())))
        return _ok(f"task #{tid} scheduled, first run {local(iso(nxt))}")

    @tool("task_list", "List active background tasks.", _obj({}, []))
    async def task_list(a):
        rows = db.all("SELECT id, title, schedule, next_run_at, last_run_at, last_result FROM tasks WHERE active = 1")
        for r in rows:
            r["next_run_at"], r["last_run_at"] = local(r["next_run_at"]), local(r["last_run_at"])
            r["last_result"] = (r["last_result"] or "")[:200]
        return _ok(rows or "none")

    @tool("task_cancel", "Stop a background task by id.", _obj({"task_id": I}, ["task_id"]))
    async def task_cancel(a):
        n = db.run("UPDATE tasks SET active = 0 WHERE id = ?", (a["task_id"],))
        return _ok("stopped" if n else "no such task")

    # ---- notifications -------------------------------------------------------

    @tool("notify", "Send a push notification to the owner's phone right now and file it in the inbox.",
          _obj({"title": S, "body": S}, ["title", "body"]))
    async def notify(a):
        db.add_inbox("task" if ctx.mode == "task" else "system", a["title"], a["body"])
        sent = push.send(a["title"], a["body"])
        ctx.notified.append(a["title"])
        return _ok(f"delivered to {sent} device(s); saved to inbox")

    # ---- notes ---------------------------------------------------------------

    @tool("note_save", "Save or overwrite a longer markdown note (recipe, trip plan, meeting summary).",
          _obj({"title": S, "content": S}, ["title", "content"]))
    async def note_save(a):
        path = notes_dir / f"{_slug(a['title'])}.md"
        path.write_text(f"# {a['title']}\n\n{a['content']}\n")
        return _ok(f"saved note '{path.stem}'")

    @tool("note_read", "Read a note by name, or list note names if name is empty.", _obj({"name": S}, ["name"]))
    async def note_read(a):
        if not a["name"].strip():
            return _ok(sorted(p.stem for p in notes_dir.glob("*.md")) or "no notes")
        path = notes_dir / f"{_slug(a['name'])}.md"
        return _ok(path.read_text()) if path.exists() else _err("no such note")

    # ---- the companion ---------------------------------------------------------

    @tool("express", "Set your companion body's facial expression and a tiny thought bubble (max ~6 words). "
          f"Use once per reply. Expressions: {', '.join(sorted(EXPRESSIONS))}.",
          _obj({"expression": S, "thought": S}, ["expression"]))
    async def express(a):
        ctx.expression = pet.express(a["expression"], a.get("thought", ""))
        return _ok("ok")

    tools = [remember, recall, forget, list_add, list_show, list_check, reminder_set, reminder_list,
             reminder_cancel, task_create, task_list, task_cancel, notify, note_save, note_read, express]
    server = create_sdk_mcp_server(SERVER_NAME, version="0.1.0", tools=tools)
    names = [f"mcp__{SERVER_NAME}__{t.name}" for t in tools]
    return server, names
