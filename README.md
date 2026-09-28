# Camena

A personal AI companion for your phone that runs on **your own Claude plan**, served from a
small server you control, and installed on the iPhone from Safari (no App Store).

It is the answer to Meta's Muse / Muse Charm pitch: an agent that sees through your
camera, talks, remembers, keeps working after you close it, and checks with you before
it does anything consequential, plus a tamagotchi you raise by using it. Feature-by-feature
comparison: [`docs/MUSE_PARITY.md`](docs/MUSE_PARITY.md).

```
iPhone (PWA on the home screen)                   your server (Docker, host:8008)
┌───────────────────────────┐   HTTPS, cookie   ┌───────────────────────────────────┐
│ companion + chat          │ ────────────────► │ FastAPI  ── SSE stream ──►        │
│ camera (getUserMedia)     │   POST /api/chat  │ Brain: Claude Agent SDK session   │
│ voice (Web Speech / TTS)  │                   │   tools: web search/fetch,        │
│ Web Push notifications    │ ◄──── push ────── │   camena MCP (memory, lists,      │
└───────────────────────────┘                   │   reminders, tasks, notes, pet),  │
                                                │   claude.ai connectors (Gmail…)   │
                                                │ Scheduler: reminders + tasks      │
                                                │ SQLite on a volume                │
                                                └────────────┬──────────────────────┘
                                                             │ CLAUDE_CODE_OAUTH_TOKEN
                                                             ▼ (your Max plan's limits)
                                                         Anthropic
```

## Get your own

Camena is one-owner software: everyone runs their own copy, on their own Claude plan.

**[Deploy on Railway](docs/RAILWAY.md)**: about 5 minutes and roughly $5/month. Railway asks you to pick a
passcode; then open the address on your iPhone, and the setup screen connects your Claude account and puts
Camena on your Home Screen. *(A one-click Deploy button goes here once the Railway template is published.)*

## Why this is allowed on a Max plan

The Claude Agent SDK used in your own projects draws from your Pro/Max usage limits
([Claude Help Center](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan);
the planned separate Agent SDK credit was paused on 2026-06-15, so today it draws from the same limits as
Claude Code). What the terms do not allow is sharing your plan: credits are per user. **Camena is
single-owner by design.** Don't hand the passcode to other people. If it ever becomes multi-user,
switch it to an API key.

## Install on the iPhone

1. Open `https://pathtools.ai/camena/` in **Safari**, enter the passcode.
2. Share → **Add to Home Screen**. Open Camena from the home-screen icon (not Safari).
3. Drawer → Settings → **Enable notifications** (iOS 16.4+; only works from the home-screen app).
4. Allow camera and microphone when first asked.

Updates ship by redeploying the server; the app picks them up on next launch.

### "Hey Siri", the Action button and the share sheet

Camena → Settings → *Hey Siri, Action button & Share sheet* shows the URL and token. In the Shortcuts app:

1. **Dictate Text**
2. **Get Contents of URL**: `https://pathtools.ai/camena/api/shortcut`, method POST, header
   `Authorization: Bearer <token>`, JSON body `text` = *Dictated Text*
3. **Speak Text**: *Contents of URL*

Name it **Ask Camena**. "Hey Siri, Ask Camena" now works hands-free (like Muse's wake word); assign it to
the Action button for the Charm's squeeze-to-talk. For a share-sheet variant, turn on *Show in Share Sheet*,
skip the dictation step, and send `url` = *Shortcut Input* for links or `image` = *Base64 Encode (Shortcut Input)*
for photos and screenshots. Anything that needs approval answers "Open Camena to approve."

## Run it

```bash
# 1. a long-lived token for your plan (run once, on any machine logged into Claude)
claude setup-token

# 2. configure
cp docker/.env.example docker/.env      # paste the token, pick a passcode

# 3. start
docker compose -f docker/docker-compose.yml up -d --build
```

Caddy (production, `pathtools.ai`), alongside the time tracker and leads stacks:

```caddy
@camena_no_slash path /camena
redir @camena_no_slash /camena/ permanent
handle_path /camena/* {
    reverse_proxy host.docker.internal:8008
}
```

`handle_path` strips `/camena`, and every URL in the app is relative, so the same build
works at the root locally and under `/camena/` in production.

### Local development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend
../.venv/bin/pytest                                   # no Claude calls
CAMENA_PASSCODE=devpass123 CAMENA_DATA_DIR=../data \
  ../.venv/bin/uvicorn app.main:app_factory --factory --port 8808 --reload
```

Locally the SDK uses whatever `claude` login the machine already has.

## Layout

| Path | What |
|---|---|
| `backend/app/agent.py` | The brain: warm Agent SDK session, streaming, approval gate, background task runner |
| `backend/app/tools.py` | Camena's own tools (in-process MCP): memory, lists, reminders, tasks, notify, notes, express |
| `backend/app/scheduler.py` | 30 s heartbeat: fires reminders, runs due tasks one at a time |
| `backend/app/schedule.py` | The tiny schedule language (`daily 07:30`, `weekdays 08:00`, `every 2h`, …) |
| `backend/app/pet.py` | The companion's stats, decay, growth stages |
| `backend/app/push.py` | VAPID keys + Web Push |
| `backend/app/main.py` | HTTP routes; also serves the PWA |
| `frontend/` | The PWA: no build step, plain ES modules |
| `docker/` | Image + compose stack |

## Safety properties

- **Passcode or nothing.** The app refuses to start without `CAMENA_PASSCODE`; every API route
  except login/health needs the session cookie (HttpOnly, SameSite=Strict, 90 days).
- **No shell, no filesystem tools.** The agent gets web search/fetch, Camena's own tools and your
  claude.ai connectors. It runs as a non-root user in its own container.
- **Approval gate.** Any tool whose name looks like it changes the outside world (send, create,
  delete, book, buy, …) is denied until you tap **Approve**; background tasks can never do it, only
  notify you.
- **Your data stays on your server**, apart from what goes to Anthropic to answer you.
