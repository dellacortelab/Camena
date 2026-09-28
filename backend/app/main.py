"""HTTP surface. The same container serves /api/* and the static PWA.

Every path is relative so the app works at the root locally and behind Caddy's
`handle_path /camena/*` in production.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import Brain
from .config import Settings, load_settings
from .db import DB, iso, utcnow
from .pet import Pet
from .push import Push
from .scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
COOKIE = "camena_session"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4


class Login(BaseModel):
    passcode: str


class Rename(BaseModel):
    name: str


class App:
    """Everything the routes need, built once at startup."""

    def __init__(self, settings: Settings):
        self.settings = settings
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.db = DB(settings.db_path)
        self.pet = Pet(self.db, settings.timezone)
        self.push = Push(self.db, settings.vapid_contact)
        self.brain = Brain(self.db, self.pet, self.push, settings)
        self.scheduler = Scheduler(self.db, self.push, self.brain, settings)


def create_app(settings: Settings | None = None, start_scheduler: bool = True) -> FastAPI:
    settings = settings or load_settings()
    state = App(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_scheduler:
            state.scheduler.start()
        yield
        await state.scheduler.stop()
        await state.brain.close_chat()

    app = FastAPI(title="Camena", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.camena = state

    # ---- auth -----------------------------------------------------------------

    def require_auth(request: Request) -> None:
        token = request.cookies.get(COOKIE)
        try:
            jwt.decode(token or "", settings.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(401, "locked")

    @app.post("/api/login")
    async def login(body: Login, request: Request, response: Response):
        if not secrets.compare_digest(body.passcode.encode(), settings.passcode.encode()):
            raise HTTPException(401, "wrong passcode")
        token = jwt.encode({"sub": "owner", "exp": utcnow() + timedelta(days=90)}, settings.jwt_secret, algorithm="HS256")
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(COOKIE, token, max_age=90 * 86400, httponly=True, samesite="strict", secure=secure)
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    authed = [Depends(require_auth)]

    # ---- state for the home screen ---------------------------------------------

    @app.get("/api/state", dependencies=authed)
    async def get_state():
        db = state.db
        return {
            "owner": settings.owner_name,
            "pet": state.pet.get(),
            "unread": db.one("SELECT COUNT(*) AS n FROM inbox WHERE read = 0")["n"],
            "vapid_public_key": state.push.public_key,
            "push_devices": state.push.count(),
            "history": list(reversed(db.all(
                "SELECT id, role, text, image, created_at FROM messages WHERE thread = 'main' ORDER BY id DESC LIMIT 40"
            ))),
        }

    # ---- chat (streamed as server-sent events over a POST) ----------------------

    @app.post("/api/chat", dependencies=authed)
    async def chat(
        text: str = Form(""),
        voice: bool = Form(False),
        approve: bool = Form(False),
        images: list[UploadFile] = File(default=[]),
    ):
        if not text.strip() and not images:
            raise HTTPException(400, "say something or show me something")
        if len(images) > MAX_IMAGES:
            raise HTTPException(400, f"at most {MAX_IMAGES} photos per message")
        saved: list[Path] = []
        for up in images:
            data = await up.read()
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(413, "photo too large")
            suffix = ".png" if (up.content_type or "").endswith("png") else ".jpg"
            path = settings.uploads_dir / f"{utcnow():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}{suffix}"
            path.write_bytes(data)
            saved.append(path)

        db = state.db
        db.log_message("main", "user", text, saved[0].name if saved else None)
        kind = "photo" if saved else ("voice" if voice else "chat")
        pet_view = state.pet.interact(kind)

        async def stream():
            yield _sse({"type": "pet", "pet": pet_view})
            final = ""
            async for event in state.brain.chat(text, saved, voice=voice, approve=approve):
                if event["type"] == "done":
                    final = event["text"]
                    event["pet"] = state.pet.get()
                yield _sse(event)
            if final:
                db.log_message("main", "assistant", final)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/chat/reset", dependencies=authed)
    async def chat_reset():
        await state.brain.reset()
        state.db.log_message("main", "event", "New conversation")
        return {"ok": True}

    @app.get("/api/uploads/{name}", dependencies=authed)
    async def upload(name: str):
        path = (settings.uploads_dir / name).resolve()
        if path.parent != settings.uploads_dir.resolve() or not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    # ---- the companion ----------------------------------------------------------

    @app.post("/api/pet/pat", dependencies=authed)
    async def pet_pat():
        return state.pet.interact("pet")

    @app.post("/api/pet/name", dependencies=authed)
    async def pet_name(body: Rename):
        return state.pet.rename(body.name)

    # ---- drawers: lists, reminders, tasks, memories, inbox ---------------------------

    @app.get("/api/lists", dependencies=authed)
    async def lists():
        rows = state.db.all("SELECT id, list_name, text, done FROM list_items WHERE done = 0 ORDER BY list_name, id")
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(r["list_name"], []).append({"id": r["id"], "text": r["text"]})
        return out

    @app.post("/api/lists/{item_id}/done", dependencies=authed)
    async def list_done(item_id: int):
        state.db.run("UPDATE list_items SET done = 1 WHERE id = ?", (item_id,))
        return {"ok": True}

    @app.get("/api/agenda", dependencies=authed)
    async def agenda():
        db = state.db
        return {
            "reminders": db.all(
                "SELECT id, text, due_at FROM reminders WHERE fired_at IS NULL AND cancelled = 0 ORDER BY due_at"),
            "tasks": db.all(
                "SELECT id, title, schedule, next_run_at, last_run_at, last_result FROM tasks WHERE active = 1 ORDER BY id"),
        }

    @app.post("/api/reminders/{rid}/cancel", dependencies=authed)
    async def reminder_cancel(rid: int):
        state.db.run("UPDATE reminders SET cancelled = 1 WHERE id = ?", (rid,))
        return {"ok": True}

    @app.post("/api/tasks/{tid}/cancel", dependencies=authed)
    async def task_cancel(tid: int):
        state.db.run("UPDATE tasks SET active = 0 WHERE id = ?", (tid,))
        return {"ok": True}

    @app.post("/api/tasks/{tid}/run", dependencies=authed)
    async def task_run_now(tid: int):
        task = state.db.one("SELECT * FROM tasks WHERE id = ? AND active = 1", (tid,))
        if not task:
            raise HTTPException(404)
        state.db.run("UPDATE tasks SET next_run_at = ? WHERE id = ?", (iso(utcnow()), tid))
        return {"ok": True, "note": "runs within 30 seconds"}

    @app.get("/api/memories", dependencies=authed)
    async def memories():
        return state.db.all("SELECT id, topic, text, created_at FROM memories ORDER BY topic, id")

    @app.delete("/api/memories/{mid}", dependencies=authed)
    async def memory_delete(mid: int):
        state.db.run("DELETE FROM memories WHERE id = ?", (mid,))
        return {"ok": True}

    @app.get("/api/inbox", dependencies=authed)
    async def inbox():
        rows = state.db.all("SELECT * FROM inbox ORDER BY id DESC LIMIT 50")
        state.db.run("UPDATE inbox SET read = 1 WHERE read = 0")
        return rows

    # ---- push -------------------------------------------------------------------------

    @app.post("/api/push/subscribe", dependencies=authed)
    async def push_subscribe(request: Request):
        sub = await request.json()
        if not isinstance(sub, dict) or "endpoint" not in sub or "keys" not in sub:
            raise HTTPException(400, "not a push subscription")
        state.push.subscribe(sub)
        return {"ok": True, "devices": state.push.count()}

    @app.post("/api/push/test", dependencies=authed)
    async def push_test():
        name = state.pet.get()["name"]
        return {"sent": state.push.send(f"{name} says hi", "Notifications work. I'll only buzz when it matters.")}

    # ---- the PWA ----------------------------------------------------------------------

    frontend = settings.frontend_dir
    if frontend.exists():
        @app.get("/")
        async def index():
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

        @app.get("/sw.js")
        async def service_worker():
            return FileResponse(frontend / "sw.js", media_type="text/javascript",
                                headers={"Cache-Control": "no-cache"})

        app.mount("/", StaticFiles(directory=frontend), name="static")

    return app


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def app_factory() -> FastAPI:
    return create_app()
