"""Tests for everything that does not need a live Claude session."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import schedule as sched
from app.agent import is_write_tool
from app.config import load_settings
from app.db import DB, iso, utcnow
from app.main import create_app
from app.pet import Pet, stage_for
from app.push import Push
from app.tools import TurnContext, build_server

DENVER = ZoneInfo("America/Denver")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMENA_PASSCODE", "hunter22")
    monkeypatch.setenv("CAMENA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAMENA_OWNER_NAME", "Dennis")
    return load_settings()


@pytest.fixture
def db(tmp_path):
    return DB(tmp_path / "t.sqlite3")


# ---- schedule ----------------------------------------------------------------

def test_daily_rolls_to_tomorrow_when_time_has_passed():
    after = datetime(2026, 9, 28, 20, 0, tzinfo=DENVER)  # Monday 20:00
    nxt = sched.next_run("daily 07:30", after, DENVER)
    assert nxt.astimezone(DENVER) == datetime(2026, 9, 29, 7, 30, tzinfo=DENVER)


def test_weekdays_skip_the_weekend():
    friday_night = datetime(2026, 10, 2, 21, 0, tzinfo=DENVER)
    nxt = sched.next_run("weekdays 08:00", friday_night, DENVER)
    assert nxt.astimezone(DENVER).strftime("%a %H:%M") == "Mon 08:00"


def test_weekly_and_interval():
    after = datetime(2026, 9, 28, 10, 0, tzinfo=DENVER)
    assert sched.next_run("weekly fri 09:00", after, DENVER).astimezone(DENVER).day == 2
    assert sched.next_run("every 2h", after, DENVER) == (after + timedelta(hours=2)).astimezone(timezone.utc)


def test_once_is_finished_after_it_fires():
    after = datetime(2026, 9, 28, 10, 0, tzinfo=DENVER)
    assert sched.next_run("once 2026-09-28T11:00", after, DENVER) is not None
    assert sched.next_run("once 2026-09-28T09:00", after, DENVER) is None


@pytest.mark.parametrize("bad", ["hourly", "daily 25:00", "every 5m", "weekly funday 09:00", ""])
def test_bad_schedules_are_rejected(bad):
    with pytest.raises(sched.ScheduleError):
        sched.validate(bad)


# ---- pet -----------------------------------------------------------------------

def test_pet_grows_and_evolves(db):
    pet = Pet(db, DENVER)
    assert pet.get()["stage"] == "egg"
    evolved = False
    for _ in range(3):
        evolved = pet.interact("photo")["evolved"] or evolved
    assert evolved and pet.get()["stage"] == "sprout"
    assert stage_for(10_000) == "muse"


def test_pet_gets_hungry_over_time(db):
    pet = Pet(db, DENVER)
    state = db.get_json("pet") or pet.get() and db.get_json("pet")
    state["updated_at"] = iso(utcnow() - timedelta(hours=30))
    state["hunger"] = 10
    db.set_json("pet", state)
    assert pet.get()["hunger"] > 50


def test_unknown_expression_falls_back(db):
    assert Pet(db, DENVER).express("smug", "heh")["expression"] == "neutral"


# ---- approval gate -----------------------------------------------------------------

@pytest.mark.parametrize("name,write", [
    ("WebSearch", False),
    ("WebFetch", False),
    ("mcp__claude_ai_Gmail__search_threads", False),
    ("mcp__claude_ai_Gmail__send_message", True),
    ("mcp__claude_ai_Google_Calendar__create_event", True),
    ("mcp__claude_ai_Google_Calendar__list_events", False),
    ("mcp__claude_ai_Google_Drive__trash_file", True),
])
def test_write_tool_detection(name, write):
    assert is_write_tool(name) is write


# ---- tools ------------------------------------------------------------------------

def _call(tool_objs, name, args):
    tool = next(t for t in tool_objs if t.name == name)
    out = asyncio.run(tool.handler(args))
    return out, out["content"][0]["text"]


@pytest.fixture
def tool_objs(settings, db, monkeypatch):
    captured = {}
    import app.tools as tools_mod

    def fake_server(name, version, tools):
        captured["tools"] = tools
        return {"type": "sdk", "name": name}

    monkeypatch.setattr(tools_mod, "create_sdk_mcp_server", fake_server)
    ctx = TurnContext(mode="chat")
    pet = Pet(db, settings.timezone)
    build_server(db, pet, Push(db, "mailto:t@example.com"), settings, ctx)
    return captured["tools"], ctx


def test_memory_roundtrip(tool_objs, db):
    tools, _ = tool_objs
    _call(tools, "remember", {"text": "Allergic to walnuts", "topic": "food"})
    _, again = _call(tools, "remember", {"text": "allergic to walnuts"})
    assert "already" in again
    _, found = _call(tools, "recall", {"query": "walnut"})
    assert "walnuts" in found
    mid = json.loads(found)[0]["id"]
    _call(tools, "forget", {"memory_id": mid})
    assert db.all("SELECT * FROM memories") == []


def test_lists(tool_objs):
    tools, _ = tool_objs
    _call(tools, "list_add", {"list_name": "Groceries", "items": ["oat milk", "limes"]})
    _, shown = _call(tools, "list_show", {"list_name": "groceries"})
    items = json.loads(shown)
    assert [i["text"] for i in items] == ["oat milk", "limes"]
    _call(tools, "list_check", {"item_ids": [items[0]["id"]]})
    _, shown = _call(tools, "list_show", {"list_name": "groceries"})
    assert [i["text"] for i in json.loads(shown)] == ["limes"]


def test_reminders_reject_the_past(tool_objs):
    tools, _ = tool_objs
    out, text = _call(tools, "reminder_set", {"text": "x", "when": "2001-01-01T09:00"})
    assert out.get("is_error")
    future = (datetime.now(DENVER) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    _, text = _call(tools, "reminder_set", {"text": "stretch", "when": future})
    assert text.startswith("reminder #")


def test_tasks_validate_schedule_and_block_recursion(tool_objs):
    tools, ctx = tool_objs
    out, _ = _call(tools, "task_create", {"title": "t", "prompt": "p", "schedule": "every 1m"})
    assert out.get("is_error")
    _, text = _call(tools, "task_create", {"title": "Flight", "prompt": "check", "schedule": "daily 07:00"})
    assert text.startswith("task #")
    ctx.mode = "task"
    out, _ = _call(tools, "task_create", {"title": "t", "prompt": "p", "schedule": "daily 07:00"})
    assert out.get("is_error")


def test_notes(tool_objs):
    tools, _ = tool_objs
    _call(tools, "note_save", {"title": "Mole Negro!", "content": "chiles, chocolate"})
    _, names = _call(tools, "note_read", {"name": ""})
    assert "mole-negro" in names
    _, body = _call(tools, "note_read", {"name": "Mole Negro!"})
    assert "chocolate" in body


# ---- HTTP -------------------------------------------------------------------------

def test_api_is_locked_until_login(settings):
    client = TestClient(create_app(settings, start_scheduler=False))
    assert client.get("api/state").status_code == 401
    assert client.post("api/login", json={"passcode": "nope"}).status_code == 401
    assert client.post("api/login", json={"passcode": "hunter22"}).status_code == 200
    state = client.get("api/state").json()
    assert state["pet"]["stage"] == "egg" and state["owner"] == "Dennis"
    assert len(state["vapid_public_key"]) > 80
    assert client.get("/").status_code == 200
    assert "Camena" in client.get("manifest.webmanifest").text


def test_chat_streams_events_with_a_fake_brain(settings):
    app = create_app(settings, start_scheduler=False)

    async def fake_chat(text, images, voice=False, approve=False, source="chat"):
        yield {"type": "tool", "name": "WebSearch", "label": "searching the web"}
        yield {"type": "text", "delta": "Hello "}
        yield {"type": "text", "delta": "there"}
        yield {"type": "done", "text": "Hello there", "expression": None}

    app.state.camena.brain.chat = fake_chat
    client = TestClient(app)
    client.post("api/login", json={"passcode": "hunter22"})
    res = client.post("api/chat", data={"text": "hi"})
    events = [json.loads(line[6:]) for line in res.text.split("\n\n") if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["pet", "tool", "text", "text", "done"]
    history = client.get("api/state").json()["history"]
    assert [(m["role"], m["text"]) for m in history] == [("user", "hi"), ("assistant", "Hello there")]


def test_passcode_is_required(tmp_path, monkeypatch):
    monkeypatch.delenv("CAMENA_PASSCODE", raising=False)
    monkeypatch.setenv("CAMENA_DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError):
        load_settings()


def test_push_signs_with_the_stored_key(db, monkeypatch):
    """A real webpush() call up to the network: proves the stored VAPID key is usable."""
    import app.push as push_mod

    push = Push(db, "mailto:t@example.com")
    sub = {"endpoint": "https://web.push.apple.com/abc",
           "keys": {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
                    "auth": "tBHItJI5svbpez7KI4CCXg"}}
    push.subscribe(sub)
    seen = {}

    class FakeResponse:
        status_code = 201
        text = ""
        headers = {}

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        seen.update(url=url, headers=headers)
        return FakeResponse()

    monkeypatch.setattr(push_mod.webpush.__globals__["requests"], "post", fake_post)
    assert push.send("t", "b") == 1
    assert seen["headers"]["Authorization"].startswith("vapid t=")
    assert Push(db, "mailto:t@example.com").public_key == push.public_key  # key persists


# ---- v0.2: Siri shortcut, audit trail, briefing, nudges ------------------------------

def _logged_in(settings, fake_chat=None):
    app = create_app(settings, start_scheduler=False)
    if fake_chat:
        app.state.camena.brain.chat = fake_chat
    client = TestClient(app)
    client.post("api/login", json={"passcode": "hunter22"})
    return app, client


def test_shortcut_needs_its_token_and_speaks_plain_text(settings):
    import base64 as b64
    seen = {}

    async def fake_chat(text, images, voice=False, approve=False, source="chat"):
        seen.update(text=text, images=images, voice=voice, source=source)
        yield {"type": "approval", "tool": "send_message", "summary": "to: anna"}
        yield {"type": "done", "text": "Sure thing.", "expression": None}

    app, client = _logged_in(settings, fake_chat)
    token = client.get("api/shortcut/token").json()["token"]
    anon = TestClient(app)  # no cookie, like the Shortcuts app
    assert anon.post("api/shortcut", json={"text": "hi"}).status_code == 401
    assert anon.post("api/shortcut", json={"text": "hi"}, headers={"Authorization": "Bearer nope"}).status_code == 401

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    res = anon.post("api/shortcut", headers={"Authorization": f"Bearer {token}"},
                    json={"text": "what is this?", "image": b64.b64encode(png).decode(), "url": "https://x.test/r"})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/plain")
    assert res.text == "Sure thing. Open Camena to approve."
    assert seen["voice"] and seen["source"] == "shortcut" and "https://x.test/r" in seen["text"]
    assert seen["images"][0].suffix == ".png" and seen["images"][0].read_bytes() == png

    # multipart works too (Shortcuts' "Form" body)
    res = anon.post("api/shortcut", headers={"Authorization": f"Bearer {token}"}, data={"text": "hello"})
    assert res.status_code == 200

    new = client.post("api/shortcut/rotate").json()["token"]
    assert new != token
    assert anon.post("api/shortcut", json={"text": "hi"}, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_morning_brief_replaces_the_previous_one(settings):
    app, client = _logged_in(settings)
    assert client.post("api/tasks/morning-brief", json={"time": "25:00"}).status_code == 400
    client.post("api/tasks/morning-brief", json={"time": "07:00"})
    client.post("api/tasks/morning-brief", json={"time": "06:30"})
    tasks = client.get("api/agenda").json()["tasks"]
    assert [(t["title"], t["schedule"]) for t in tasks] == [("Morning briefing", "daily 06:30")]


def test_actions_are_listed(settings):
    app, client = _logged_in(settings)
    app.state.camena.db.log_action("chat", "send_message", "to: anna", "blocked")
    rows = client.get("api/actions").json()
    assert rows[0]["tool"] == "send_message" and rows[0]["outcome"] == "blocked"


def test_audit_logs_only_auto_allowed_calls(settings):
    from claude_agent_sdk import ToolUseBlock

    app = create_app(settings, start_scheduler=False)
    brain, db = app.state.camena.brain, app.state.camena.db
    allowed = {"WebSearch", "mcp__camena__express"}
    brain._audit("chat", ToolUseBlock(id="1", name="WebSearch", input={"query": "rain lisbon"}), allowed)
    brain._audit("chat", ToolUseBlock(id="2", name="mcp__camena__express", input={"expression": "happy"}), allowed)
    brain._audit("chat", ToolUseBlock(id="3", name="mcp__x__send_message", input={}), allowed)  # gate logs this one
    assert [(a["tool"], a["outcome"]) for a in db.all("SELECT * FROM actions")] == [("WebSearch", "ran")]


def test_nudge_once_a_day_in_daytime_after_silence(settings):
    app = create_app(settings, start_scheduler=False)
    st = app.state.camena
    sent = []
    st.push.send = lambda title, body, url="./": sent.append(body) or 1
    noon = datetime(2026, 9, 30, 12, 0, tzinfo=DENVER).astimezone(timezone.utc)
    st.db.run("INSERT INTO messages(thread, role, text, created_at) VALUES('main','user','hi',?)",
              (iso(noon - timedelta(hours=3)),))
    assert not st.scheduler.nudge(noon)                       # talked 3h ago
    st.db.run("UPDATE messages SET created_at = ?", (iso(noon - timedelta(hours=30)),))
    assert not st.scheduler.nudge(noon.replace(hour=5))       # 23:00 local: asleep
    assert st.scheduler.nudge(noon)
    assert not st.scheduler.nudge(noon + timedelta(hours=2))  # already nudged today
    assert len(sent) == 1 and "Cam" in sent[0]
