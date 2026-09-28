"""The relayed sign-in, driven against a fake `claude setup-token`."""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap

import pytest

from app.claude_auth import ClaudeAuth
from app.db import DB

FAKE_TOKEN = "sk-ant-oat01-" + "A" * 60

FAKE_CLI = textwrap.dedent(f"""\
    #!{sys.executable}
    import sys
    assert sys.argv[1:] == ["setup-token"], sys.argv
    print("\\x1b[1mWelcome to Claude Code\\x1b[0m")
    print("Browser didn't open? Use the url below to sign in (c to copy)")
    print()
    print("https://claude.com/cai/oauth/authorize?code=true&client_id=abc&state=xyz")
    print()
    sys.stdout.write("Paste code here if prompted > "); sys.stdout.flush()
    code = sys.stdin.readline().strip()
    if code == "good#code":
        print("\\nLong-lived authentication token created successfully!")
        print("Your OAuth token (valid for 1 year):\\n\\n{FAKE_TOKEN}\\n")
    else:
        # Like the real CLI: report, then wait for Enter instead of exiting.
        sys.stdout.write("\\nOAuth error: Request failed with status code 400Press Enter to retry.")
        sys.stdout.flush()
        sys.stdin.readline()
""")


@pytest.fixture
def auth(tmp_path, monkeypatch):
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    cli = tmp_path / "claude"
    cli.write_text(FAKE_CLI)
    cli.chmod(0o755)
    a = ClaudeAuth(DB(tmp_path / "t.sqlite3"), cli=str(cli))
    a._cli_login = False  # no machine login in tests
    yield a
    a.cancel_login()


def test_relay_hands_out_the_url_and_stores_the_token(auth):
    async def go():
        url = await auth.start_login()
        assert url == "https://claude.com/cai/oauth/authorize?code=true&client_id=abc&state=xyz"
        return await auth.finish_login("good#code")

    assert asyncio.run(go()) == FAKE_TOKEN
    assert auth.method() == "subscription"
    assert auth.sdk_env() == {"CLAUDE_CODE_OAUTH_TOKEN": FAKE_TOKEN}


def test_relay_reports_a_bad_code(auth):
    async def go():
        await auth.start_login()
        await auth.finish_login("wrong#code")

    with pytest.raises(RuntimeError, match="didn't accept"):
        asyncio.run(go())
    assert auth.method() is None


def test_finish_without_start_is_a_clear_error(auth):
    with pytest.raises(RuntimeError, match="expired"):
        asyncio.run(auth.finish_login("good#code"))


def test_pasted_credentials_are_validated(auth):
    with pytest.raises(ValueError):
        auth.save_token("hello")
    auth.save_api_key("sk-ant-api03-" + "b" * 40)
    assert auth.method() == "api-key" and "ANTHROPIC_API_KEY" in auth.sdk_env()
    auth.save_token(FAKE_TOKEN)  # switching replaces the key
    assert auth.sdk_env() == {"CLAUDE_CODE_OAUTH_TOKEN": FAKE_TOKEN}
    auth.disconnect()
    assert auth.method() is None and auth.sdk_env() == {}


def test_environment_wins(auth, monkeypatch):
    auth.save_token(FAKE_TOKEN)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-" + "Z" * 40)
    assert auth.method() == "env-token" and auth.sdk_env() == {}
