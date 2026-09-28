"""Connecting Camena to the owner's Claude account from a phone.

The server is headless, so the sign-in is relayed: we run `claude setup-token`
(the Claude Code CLI bundled with the Agent SDK) in a pseudo-terminal, hand
the sign-in URL it prints to the phone, and type the code the owner pastes
back into it. The CLI prints a 1-year token, which we keep in the database and
pass to every Agent SDK session.

The owner signs in on claude.ai directly; their password never touches Camena.
Alternatives: paste a token made with `claude setup-token` elsewhere, or an
Anthropic API key.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time
from pathlib import Path

from .db import DB

log = logging.getLogger("camena.claude_auth")

TOKEN_KEY = "claude_token"
API_KEY_KEY = "anthropic_api_key"
TOKEN_RE = re.compile(r"sk-ant-oat\d*-[A-Za-z0-9_\-]{20,}")
API_KEY_RE = re.compile(r"^sk-ant-api\d*-[A-Za-z0-9_\-]{20,}$")
URL_RE = re.compile(r"https://\S*oauth/authorize\S*")
# What the CLI prints when a pasted code is rejected (it then waits for Enter to retry).
ERROR_RE = re.compile(r"(OAuth error:.*?)(?:Press Enter|$)", re.S)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[=>()][0-9A-Za-z]?")
FLOW_TIMEOUT = 15 * 60


def bundled_cli() -> str:
    """The Claude Code binary shipped inside claude_agent_sdk, else one on PATH."""
    import claude_agent_sdk

    path = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if path.exists():
        return str(path)
    found = shutil.which("claude")
    if not found:
        raise RuntimeError("Claude Code CLI not found")
    return found


def _clean(raw: bytes) -> str:
    return ANSI_RE.sub("", raw.decode(errors="replace")).replace("\r", "")


class SetupTokenFlow:
    """One in-flight `claude setup-token` run inside a pseudo-terminal."""

    def __init__(self, cli: str):
        self.cli = cli
        self.buf = b""
        self.started = time.monotonic()
        self._home = tempfile.mkdtemp(prefix="camena-auth-")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # child
            env = {"HOME": self._home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "TERM": "xterm-256color", "BROWSER": "/bin/false"}
            os.execve(cli, [cli, "setup-token"], env)
        # A very wide terminal so the CLI never wraps the URL across lines.
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 4000, 0, 0))
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while True:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.5)
                if not ready:
                    if not self.alive():
                        return
                    continue
                chunk = os.read(self.fd, 65536)
            except OSError:
                return
            if not chunk:
                return
            with self._lock:
                self.buf += chunk

    def text(self) -> str:
        with self._lock:
            return _clean(self.buf)

    def alive(self) -> bool:
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False

    def expired(self) -> bool:
        return time.monotonic() - self.started > FLOW_TIMEOUT

    async def wait_for(self, pattern: re.Pattern, timeout: float) -> re.Match | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            match = pattern.search(self.text())
            if match:
                return match
            if not self.alive() and not self._reader.is_alive():
                return pattern.search(self.text())
            await asyncio.sleep(0.2)
        return None

    def send(self, line: str) -> None:
        os.write(self.fd, line.encode() + b"\r")

    def close(self) -> None:
        if self.alive():
            try:
                os.kill(self.pid, signal.SIGTERM)
                os.waitpid(self.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        shutil.rmtree(self._home, ignore_errors=True)


class ClaudeAuth:
    def __init__(self, db: DB, cli: str | None = None):
        self.db = db
        self._cli = cli
        self._flow: SetupTokenFlow | None = None
        self._cli_login: bool | None = None

    @property
    def cli(self) -> str:
        return self._cli or bundled_cli()

    # ---- what the Agent SDK should use -------------------------------------------

    def method(self) -> str | None:
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return "env-token"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "env-api-key"
        if self.db.get_json(TOKEN_KEY):
            return "subscription"
        if self.db.get_json(API_KEY_KEY):
            return "api-key"
        if self._has_cli_login():
            return "cli-login"
        return None

    def sdk_env(self) -> dict[str, str]:
        """Extra environment for Agent SDK sessions (empty = use the process env / CLI login)."""
        token = self.db.get_json(TOKEN_KEY)
        if token and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return {"CLAUDE_CODE_OAUTH_TOKEN": token}
        key = self.db.get_json(API_KEY_KEY)
        if key and not os.environ.get("ANTHROPIC_API_KEY"):
            return {"ANTHROPIC_API_KEY": key}
        return {}

    def _has_cli_login(self) -> bool:
        """A machine where someone already ran `claude login` (local development)."""
        if self._cli_login is None:
            try:
                out = subprocess.run([self.cli, "auth", "status"], capture_output=True, text=True, timeout=20)
                self._cli_login = '"loggedIn": true' in out.stdout
            except (OSError, subprocess.SubprocessError, RuntimeError):
                self._cli_login = False
        return self._cli_login

    def status(self) -> dict:
        method = self.method()
        return {"connected": method is not None, "method": method, "verified": self.db.get_json("claude_verified")}

    # ---- relayed sign-in ----------------------------------------------------------------

    async def start_login(self) -> str:
        """Start `claude setup-token`; returns the claude.ai sign-in URL to open on the phone."""
        self.cancel_login()
        self._flow = SetupTokenFlow(self.cli)
        match = await self._flow.wait_for(URL_RE, timeout=45)
        if not match:
            tail = self._flow.text()[-400:]
            self.cancel_login()
            raise RuntimeError(f"Claude Code did not offer a sign-in link. Output: {tail!r}")
        return match.group(0).split("Paste")[0]

    async def finish_login(self, code: str) -> str:
        flow = self._flow
        if flow is None or flow.expired() or not flow.alive():
            self.cancel_login()
            raise RuntimeError("That sign-in expired. Tap “Get sign-in link” again.")
        code = code.strip()
        if not code or any(c.isspace() for c in code):
            raise ValueError("Paste the whole code from the Claude page.")
        before = len(flow.text())
        flow.send(code)
        outcome = re.compile(f"{TOKEN_RE.pattern}|{ERROR_RE.pattern}", re.S)
        await flow.wait_for(outcome, timeout=60)
        output = flow.text()[before:]
        self.cancel_login()
        token = TOKEN_RE.search(output)
        if not token:
            err = ERROR_RE.search(output)
            reason = err.group(1).strip() if err else (output.strip().splitlines() or ["no response"])[-1]
            raise RuntimeError(f"Claude didn't accept that code ({reason[:160]}). Get a new link and try again.")
        self.save_token(token.group(0))
        return token.group(0)

    def cancel_login(self) -> None:
        if self._flow is not None:
            self._flow.close()
            self._flow = None

    # ---- pasted credentials ----------------------------------------------------------

    def save_token(self, token: str) -> None:
        token = token.strip()
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("That doesn't look like a Claude token (it starts with sk-ant-oat).")
        self.db.set_json(TOKEN_KEY, token)
        self.db.set_json(API_KEY_KEY, None)
        self.db.set_json("claude_verified", None)

    def save_api_key(self, key: str) -> None:
        key = key.strip()
        if not API_KEY_RE.match(key):
            raise ValueError("That doesn't look like an Anthropic API key (it starts with sk-ant-api).")
        self.db.set_json(API_KEY_KEY, key)
        self.db.set_json(TOKEN_KEY, None)
        self.db.set_json("claude_verified", None)

    def disconnect(self) -> None:
        self.db.set_json(TOKEN_KEY, None)
        self.db.set_json(API_KEY_KEY, None)
        self.db.set_json("claude_verified", None)
