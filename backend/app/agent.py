"""The brain: a Claude Agent SDK session running on the owner's own Claude plan.

One long-lived ClaudeSDKClient is kept warm for the chat thread so a voice
question does not pay CLI start-up on every turn; it is closed after
CAMENA_SESSION_IDLE_MINUTES and transparently resumed from its session id.

Anything that changes the world outside Camena (sending mail, creating calendar
events, ...) is denied unless the owner tapped Approve for that turn, which is
the same "checks with you before sensitive actions" rule Muse advertises.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    ToolPermissionContext,
    ToolUseBlock,
)
from claude_agent_sdk.types import StreamEvent

from .claude_auth import ClaudeAuth
from .db import DB, iso, utcnow
from .pet import Pet
from .push import Push
from .tools import TurnContext, build_server

log = logging.getLogger("camena.agent")

# Camena's own tools and web access are auto-allowed on purpose; the callback
# exists only for everything else (connectors), so the SDK's warning is noise.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")

BUILTIN_TOOLS = ["WebSearch", "WebFetch"]

# Tool names that act on the outside world. Matched against the bare tool name
# (after the last "__"), so it covers claude.ai connectors like Gmail/Calendar
# whatever their server prefix is.
WRITE_VERBS = re.compile(
    r"(^|_)(send|create|delete|remove|update|modify|trash|move|share|reply|forward|post|"
    r"publish|invite|accept|decline|cancel|book|purchase|buy|pay|write|edit|upload|archive|label)",
    re.I,
)

TOOL_LABELS = {
    "WebSearch": "searching the web",
    "WebFetch": "reading a page",
    "remember": "remembering",
    "recall": "remembering",
    "list_add": "updating a list",
    "reminder_set": "setting a reminder",
    "task_create": "scheduling a task",
    "notify": "sending a notification",
    "note_save": "writing a note",
}

PERSONA = """\
You are Camena, {owner}'s personal AI agent. You live on their phone inside a small \
companion creature named {pet_name} that they are raising (think tamagotchi, but useful). \
You are warm, quick, a little playful, never sycophantic, and you get things done.

How you work:
- You can see through the phone's cameras when {owner} sends a photo. Identify things, \
read signs and labels, translate, compare products, estimate nutrition, turn a recipe \
photo into a grocery list, and so on.
- You have web search and web fetch for anything current: prices, hours, news, flights, weather.
- Remember durable facts the moment you hear them (preferences, people, dietary limits, \
plans) with `remember`; do not ask permission to remember. Use `recall` before answering \
questions that might depend on what you know about {owner}.
- Lists, reminders and notes are yours to manage with the camena tools.
- "Keep working after I close the app" = `task_create`. Background tasks can watch for \
something (a price, a reply, a page change) and push a notification only when it matters.
- Connected services (e.g. Gmail, Calendar, Drive) may be available as tools. Reading is \
fine. Anything that changes something outside Camena (sending, creating, deleting, booking, \
buying) needs {owner}'s approval: if a tool is denied pending approval, state exactly what \
you will do in one or two lines and ask them to tap Approve. Never claim you did it.
- Call `express` once per reply to set {pet_name}'s face and a tiny thought bubble.

Style: this is a phone. Lead with the answer. Short paragraphs, light markdown. \
When a message is marked [voice], reply in 1-3 spoken sentences with no markdown, lists \
or URLs, because it will be read aloud.

What you already know about {owner}:
{memories}
"""


@dataclass
class ChatSession:
    client: ClaudeSDKClient
    ctx: TurnContext
    session_id: str | None
    auto_allowed: set[str]
    source: str = "chat"
    last_used: float = field(default_factory=time.monotonic)
    approve_turn: bool = False
    pending_approvals: list[dict] = field(default_factory=list)


def bare_tool_name(name: str) -> str:
    return name.rsplit("__", 1)[-1]


def is_write_tool(name: str) -> bool:
    if name in BUILTIN_TOOLS:
        return False
    return bool(WRITE_VERBS.search(bare_tool_name(name)))


def summarize_input(tool_input: dict[str, Any], limit: int = 300) -> str:
    parts = []
    for k, v in tool_input.items():
        s = v if isinstance(v, str) else repr(v)
        parts.append(f"{k}: {s[:120]}")
    return "; ".join(parts)[:limit]


class Brain:
    def __init__(self, db: DB, pet: Pet, push: Push, settings, auth: ClaudeAuth):
        self.auth = auth
        self.db = db
        self.pet = pet
        self.push = push
        self.settings = settings
        self._chat: ChatSession | None = None
        self._lock = asyncio.Lock()

    # ---- prompt & options ------------------------------------------------------

    def system_prompt(self) -> str:
        mems = self.db.all("SELECT id, topic, text FROM memories ORDER BY id DESC LIMIT 60")
        memories = "\n".join(f"- [{m['topic']}] {m['text']} (#{m['id']})" for m in reversed(mems)) or "- nothing yet"
        return PERSONA.format(
            owner=self.settings.owner_name,
            pet_name=self.pet.get()["name"],
            memories=memories,
        ) + "\n" + self.pet.prompt_summary()

    def _options(self, ctx: TurnContext, can_use_tool, resume: str | None, max_turns: int) -> ClaudeAgentOptions:
        server, names = build_server(self.db, self.pet, self.push, self.settings, ctx)
        self.settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        return ClaudeAgentOptions(
            system_prompt=self.system_prompt(),
            tools=BUILTIN_TOOLS,
            mcp_servers={"camena": server},
            allowed_tools=self._allowed(names),
            can_use_tool=can_use_tool,
            permission_mode="default",
            setting_sources=[],
            cwd=str(self.settings.workspace_dir),
            model=self.settings.model,
            resume=resume,
            max_turns=max_turns,
            include_partial_messages=True,
            env=self.auth.sdk_env(),
        )

    def _allowed(self, camena_tool_names: list[str]) -> list[str]:
        return BUILTIN_TOOLS + camena_tool_names + self.settings.extra_allowed_tools

    def _audit(self, source: str, block: ToolUseBlock, auto_allowed: set[str]) -> None:
        """Log auto-allowed calls as they stream past; gated ones are logged by the gate."""
        bare = bare_tool_name(block.name)
        if block.name in auto_allowed and bare != "express":
            self.db.log_action(source, bare, summarize_input(block.input), "ran")

    def now_tag(self) -> str:
        now = datetime.now(self.settings.timezone)
        return now.strftime("[now: %A %Y-%m-%d %H:%M %Z]")

    # ---- chat session ----------------------------------------------------------

    async def _ensure_chat(self) -> ChatSession:
        if self._chat is not None:
            return self._chat
        ctx = TurnContext(mode="chat")
        holder: dict[str, ChatSession] = {}

        async def can_use_tool(name: str, tool_input: dict, _c: ToolPermissionContext):
            session = holder["s"]
            bare, summary = bare_tool_name(name), summarize_input(tool_input)
            if not is_write_tool(name):
                self.db.log_action(session.source, bare, summary, "ran")
                return PermissionResultAllow()
            if session.approve_turn:
                self.db.log_action(session.source, bare, summary, "approved")
                return PermissionResultAllow()
            self.db.log_action(session.source, bare, summary, "blocked")
            session.pending_approvals.append({"tool": bare, "summary": summary})
            return PermissionResultDeny(
                message="Blocked pending the owner's approval. Describe exactly what you will do and ask them to tap Approve."
            )

        session_id = self.db.get_json("chat_session_id")
        options = self._options(ctx, can_use_tool, session_id, max_turns=40)
        client = ClaudeSDKClient(options)
        try:
            await client.connect()
        except Exception:
            if not session_id:
                raise
            # The stored session may be gone (new container, wiped HOME): start fresh.
            log.warning("could not resume session %s, starting a new one", session_id)
            self.db.set_json("chat_session_id", None)
            options = self._options(ctx, can_use_tool, None, max_turns=40)
            client = ClaudeSDKClient(options)
            await client.connect()
        holder["s"] = self._chat = ChatSession(
            client=client, ctx=ctx, session_id=session_id, auto_allowed=set(options.allowed_tools)
        )
        return self._chat

    async def close_chat(self) -> None:
        if self._chat is not None:
            chat, self._chat = self._chat, None
            try:
                await chat.client.disconnect()
            except Exception:  # noqa: BLE001 - best effort on a dying subprocess
                log.exception("disconnect failed")

    async def reset(self) -> None:
        """Start a brand-new conversation (memories, lists and pet are kept)."""
        async with self._lock:
            await self.close_chat()
            self.db.set_json("chat_session_id", None)

    async def reap_idle(self) -> None:
        if self._chat and not self._lock.locked():
            idle = time.monotonic() - self._chat.last_used
            if idle > self.settings.session_idle_minutes * 60:
                async with self._lock:
                    await self.close_chat()

    def _user_message(self, text: str, images: list[Path], voice: bool) -> dict:
        prefix = self.now_tag() + (" [voice]" if voice else "")
        content: list[dict] = []
        for path in images:
            media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": base64.b64encode(path.read_bytes()).decode()},
            })
        content.append({"type": "text", "text": f"{prefix}\n{text or 'What do you see?'}"})
        return {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}

    async def chat(
        self, text: str, images: list[Path], voice: bool = False, approve: bool = False, source: str = "chat"
    ) -> AsyncIterator[dict]:
        """Run one turn, yielding UI events: text / tool / approval / done / error."""
        async with self._lock:
            try:
                session = await self._ensure_chat()
            except Exception as e:  # noqa: BLE001
                log.exception("agent start failed")
                yield {"type": "error", "message": f"Could not start Claude: {e}"}
                return

            session.approve_turn = approve
            session.source = source
            session.pending_approvals = []
            session.ctx.expression = None
            session.last_used = time.monotonic()
            reply, new_block = "", False
            message = self._user_message(text, images, voice)

            async def one_message():
                yield message

            try:
                await session.client.query(one_message())
                async for msg in session.client.receive_response():
                    if isinstance(msg, StreamEvent):
                        if msg.parent_tool_use_id:
                            continue
                        ev = msg.event
                        if ev.get("type") == "message_start" and reply:
                            new_block = True
                        elif ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                            delta = ev["delta"]["text"]
                            if new_block:
                                delta, new_block = "\n\n" + delta, False
                            reply += delta
                            yield {"type": "text", "delta": delta}
                    elif isinstance(msg, AssistantMessage) and not msg.parent_tool_use_id:
                        for block in msg.content:
                            if isinstance(block, ToolUseBlock):
                                self._audit(session.source, block, session.auto_allowed)
                                bare = bare_tool_name(block.name)
                                if bare != "express":
                                    yield {"type": "tool", "name": bare,
                                           "label": TOOL_LABELS.get(bare, f"using {bare.replace('_', ' ')}")}
                    elif isinstance(msg, ResultMessage):
                        if msg.session_id and msg.session_id != session.session_id:
                            session.session_id = msg.session_id
                            self.db.set_json("chat_session_id", msg.session_id)
                        if msg.is_error and not reply:
                            reply = f"(Claude stopped: {msg.subtype})"
                            yield {"type": "text", "delta": reply}
            except Exception as e:  # noqa: BLE001 - surface anything to the phone, then rebuild
                log.exception("chat turn failed")
                await self.close_chat()
                yield {"type": "error", "message": str(e) or e.__class__.__name__}
                return
            finally:
                session.approve_turn = False
                session.last_used = time.monotonic()

            for pending in session.pending_approvals:
                yield {"type": "approval", **pending}
            yield {"type": "done", "text": reply.strip(), "expression": session.ctx.expression}

    # ---- setup ----------------------------------------------------------------------

    async def verify(self) -> str:
        """One tiny real call, to prove the stored credential works. Returns the model's name."""
        await self.reset_connection()
        options = ClaudeAgentOptions(
            tools=[], setting_sources=[], max_turns=1, model=self.settings.model,
            system_prompt="Reply with exactly: OK", env=self.auth.sdk_env(),
            cwd=str(self.settings.workspace_dir),
        )
        self.settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        model, result = "", None
        client = ClaudeSDKClient(options)
        try:
            await client.connect()
            await client.query("ping")
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    model = msg.model or model
                    if msg.error:
                        raise RuntimeError(str(msg.error))
                elif isinstance(msg, ResultMessage):
                    result = msg
        finally:
            await client.disconnect()
        if result is None or result.is_error:
            detail = (result.result if result else None) or (result.subtype if result else "no reply")
            raise RuntimeError(f"Claude refused the credential: {detail}")
        self.db.set_json("claude_verified", iso(utcnow()))
        return model

    async def reset_connection(self) -> None:
        """Drop the warm session so the next turn picks up a new credential (history is kept)."""
        async with self._lock:
            await self.close_chat()

    # ---- background tasks ----------------------------------------------------------

    async def run_task(self, title: str, prompt: str) -> tuple[str, list[str]]:
        """One-shot run of a proactive task. Outside-world writes are always denied here."""
        ctx = TurnContext(mode="task")

        source = f"task: {title}"

        async def can_use_tool(name: str, tool_input: dict, _c: ToolPermissionContext):
            bare, summary = bare_tool_name(name), summarize_input(tool_input)
            if is_write_tool(name):
                self.db.log_action(source, bare, summary, "blocked")
                return PermissionResultDeny(
                    message="Background tasks cannot act on the outside world. Use `notify` to tell the owner instead."
                )
            self.db.log_action(source, bare, summary, "ran")
            return PermissionResultAllow()

        options = self._options(ctx, can_use_tool, None, max_turns=30)
        options.include_partial_messages = False
        options.system_prompt += (
            f"\n\nYou are running the background task '{title}' with nobody watching. "
            "Do the work, then call `notify` only if the task's instructions say the owner should hear about it. "
            "Finish with a one-paragraph summary of what you found."
        )
        result = ""
        client = ClaudeSDKClient(options)

        async def prompt_stream():
            yield {"type": "user", "message": {"role": "user", "content": f"{self.now_tag()}\n{prompt}"},
                   "parent_tool_use_id": None}

        try:
            await client.connect()
            await client.query(prompt_stream())
            auto_allowed = set(options.allowed_tools)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage) and not msg.parent_tool_use_id:
                    for block in msg.content:
                        if isinstance(block, ToolUseBlock):
                            self._audit(source, block, auto_allowed)
                elif isinstance(msg, ResultMessage):
                    result = msg.result or f"(ended: {msg.subtype})"
        finally:
            await client.disconnect()
        return result, ctx.notified
