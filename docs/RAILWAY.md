# Camena on Railway

Each person runs **their own** Camena, in **their own** Railway account, connected to **their own**
Claude subscription. Nobody else holds their token or their data; that's what keeps this in line with
Anthropic's rule against third-party apps offering claude.ai login
([Agent SDK docs](https://code.claude.com/docs/en/agent-sdk/overview)). Before promoting Camena
publicly, ask Anthropic, since the docs say "unless previously approved".

Cost: Railway's Hobby plan is $5/month including $5 of usage. Camena idles at ~80 MB; while you use it,
the Claude Code process and the voice model (~300 MB, unloaded after 15 quiet minutes) add to that.
Light use should stay near the included $5 (check Railway's current pricing and your usage page).

---

## For the person deploying Camena

**1. Deploy.** Open **[railway.com/deploy/CeHh99](https://railway.com/deploy/CeHh99)**. Sign in to Railway (GitHub sign-in is
fastest) and add a card if asked. Railway shows one field:

| Variable | What to type |
|---|---|
| `CAMENA_PASSCODE` | A passcode you'll remember, 6+ characters. It's the lock on your Camena. |

Click **Deploy**. It takes 3–5 minutes to build the first time.

**2. Open it on your iPhone.** In Railway, open the Camena service → **Settings → Networking**: the
`…up.railway.app` address. Open it in **Safari** on the iPhone and enter your passcode.

**3. The setup screen** walks you through:
1. **You**: your name, timezone and your companion's name.
2. **Claude**: tap *Get my sign-in link* → *Open claude.ai* → sign in with your Claude account →
   *Authorize* → copy the code → paste it back → *Connect*. Camena makes one tiny test call to confirm it
   works.
3. **Home Screen**: Share → *Add to Home Screen*, then open Camena from the new icon.

Then open the drawer → Settings → **Enable notifications**.

---

## For the publisher (one time; creates the Deploy button)

A Railway template can only be made in the Railway dashboard.

1. **New Project → Deploy from GitHub repo →** `dellacortelab/Camena`. Railway reads `railway.json` and builds
   `docker/Dockerfile`.
2. On the service, **Variables → New Variable**: `CAMENA_PASSCODE` = anything (it's for this test copy).
3. **Right-click the service → Attach Volume**, mount path **`/data`**. Everything Camena keeps lives there:
   the database, the Claude token and the session history.
4. **Settings → Networking → Generate Domain**. Railway gives you HTTPS; the iPhone needs it for
   the camera, microphone and notifications.
5. Wait for the deploy to go green, open the domain, and check the setup screen appears.
6. **Project Settings → Generate Template from Project.** In the template editor:
   - `CAMENA_PASSCODE`: clear the value, mark it **required**, description
     "Choose a passcode (6+ characters). It locks your Camena."
   - Optional, with defaults: `CAMENA_OWNER_NAME`, `CAMENA_TIMEZONE`.
   - Confirm the volume at `/data` and public HTTP networking are included.
7. **Create** → copy the template URL and put it in the README's Deploy button:
   `[![Deploy on Railway](https://railway.com/button.svg)](<template URL>)`.
   Railway also lists `PORT` as a user-filled variable: set it to `8080` in the template so deployers
   only choose a passcode. (Camena's template: `https://railway.com/deploy/CeHh99`, created 2026-09-29.)

**Source visibility.** Railway can only build a private GitHub repo for accounts that have access to it.
For anyone else to deploy, either make the repo public, or publish the image (e.g. to GHCR, public) and
point the template's service at the image instead of the repo.

## Updating

Push to `main`. The publisher's own service redeploys automatically. Other people's copies were created
from the template, so each owner redeploys from their Railway dashboard.

## If something goes wrong

- **"Claude didn't accept that code"**: codes are single-use and expire quickly. Tap *Get a new
  sign-in link*, then copy the code right after authorizing.
- **Sign-in link never appears**: Railway → the service → **Deployments → View logs**, and look for
  `camena.claude_auth`.
- **Notifications don't arrive**: only the Home Screen app can receive them (iOS 16.4+), and only
  after *Enable notifications*.
- **Forgot the passcode**: Railway → Variables → change `CAMENA_PASSCODE` → redeploy. Your data stays.
