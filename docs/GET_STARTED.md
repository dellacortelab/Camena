# Get your own Camena

Camena is a personal AI companion for your iPhone: it sees through your camera, talks with a natural
voice, remembers what matters to you, reminds you of things, and keeps an eye on things for you in the
background. It even grows up as you use it.

It thinks with **your own Claude subscription** and runs on **your own small server**, so nobody
else sees your conversations and there's no extra AI bill. There's no App Store either: you install
it straight from Safari.

**About 15 minutes. What you need:**

| | |
|---|---|
| An iPhone | iOS 17 or later (16.4+ works, but notifications and voice are best on 17+) |
| A Claude subscription | **Pro or Max**, on your own account ([claude.ai](https://claude.ai)) |
| A Railway account | Railway hosts your server: about **$5/month**, with a free trial to start. Needs a card |
| A computer (recommended) | Railway's website is easier on a big screen. Everything else happens on the phone |

> **Everyone runs their own copy.** Don't share your Camena or your Claude account with someone else:
> Claude subscriptions are personal. Your partner or friend deploys their own in 15 minutes.

---

## Part 1 · Create your server (computer, ~7 minutes)

1. Click **[Deploy on Railway](../README.md#get-your-own)** (the purple button in the README).
2. Railway asks you to sign in. **Continue with GitHub** or with email is fine. New accounts start with a
   trial credit; add a card when asked, which keeps the server running after the trial.
3. You'll see one setting, **`CAMENA_PASSCODE`**. Type a passcode you'll remember (6+ characters).
   It's the lock on your Camena; anyone with your web address *and* this passcode could use your Claude.
4. Click **Deploy**. The first build takes **5–8 minutes** (it downloads the voice model). You can walk
   away; closing the page doesn't stop it.
5. When the service shows **Online**, open it → **Settings → Networking** and copy your address, which
   looks like `camena-production-xxxx.up.railway.app`. Send it to your phone (AirDrop, iMessage to
   yourself, or email).

## Part 2 · Set it up on your iPhone (~5 minutes)

1. Open the address in **Safari** (not Chrome) and enter your passcode.
2. **You:** your name, your timezone (filled in for you), and a name for your companion.
3. **Claude:** this connects *your* Claude subscription.
   1. Tap **Get my sign-in link**, then **Open claude.ai to sign in**.
   2. Sign in with your Claude account and tap **Authorize**.
   3. Claude shows a code. **Copy it**, go back to the Camena tab, **paste**, and tap **Connect**.
   4. Wait for the green **✓ Connected** box (up to 20 seconds).

   *If it says the code wasn't accepted:* tap **Get a new sign-in link** and try once more. Copy the
   code right after authorizing, since codes expire within minutes.
4. **Home Screen:** tap Safari's **Share** button → **Add to Home Screen** → **Add**.
5. Close Safari and **open Camena from its new icon**. Enter your passcode once more (the Home Screen
   app keeps its own login).
6. **Stop the camera and microphone questions.** iOS forgets a web app's permissions whenever it
   unloads it, so without this it asks again after every screen lock. On the iPhone:
   **Settings → Apps → Safari → Settings for Websites → Camera → Allow**, and the same for
   **Microphone → Allow**.
7. ☰ menu → **Settings**:
   - **Enable notifications** → Allow, so reminders and background alerts reach you.
   - **Voice:** pick one of the *Camena voices* and tap ▶︎ to hear it.

That's it. Say hi. 👋

## Part 3 · Things to try

- **Point and ask:** camera → **Snap & ask**, then talk: *"Is this vegetarian?"*, *"What does this sign say?"*
- **Just talk:** tap 🎙. Turn on **Conversation mode** in Settings to go back and forth hands-free.
- **Remember:** *"My sister Anna lives in Lisbon and is allergic to walnuts."* (See ☰ → Memory.)
- **Remind:** *"Remind me at 6 to call mom."*
- **Watch for me:** *"Every morning at 7, check the weather and tell me only if it will rain."*
- **Morning briefing:** Settings → Morning briefing → **Set**.
- **Hey Siri:** Settings → *Hey Siri, Action button & Share sheet* shows how to make a Shortcut, so
  *"Hey Siri, ask Camena…"* works, or put it on the iPhone's Action button.
- **Lists:** *"Add oat milk and limes to groceries"*, or show it a recipe and ask for a shopping list.

Anything that would act on the outside world (sending, booking, deleting) waits for you to tap
**Approve**, and ☰ → **Activity** shows everything it has done.

## If something's off

| Problem | Fix |
|---|---|
| The deploy failed | Railway → your service → **Deployments → View logs**. Most often it's a passcode shorter than 6 characters |
| "Claude didn't accept that code" | Tap **Get a new sign-in link** and try again, copying the code right after authorizing |
| No sound | Turn silent mode off. Pick a *Camena voice* in Settings and tap ▶︎ |
| It asks for camera/mic permission every time | iPhone Settings → Apps → Safari → Settings for Websites → **Camera: Allow** and **Microphone: Allow** |
| The mic does nothing | Same setting as above; or use the 🎙 key on the iPhone keyboard |
| The screen locks while it's talking | Update iOS: keeping the screen awake from a Home Screen app needs a recent version |
| No notifications | They only work from the **Home Screen icon**, after **Enable notifications** |
| Forgot the passcode | Railway → Variables → change `CAMENA_PASSCODE`. Your data is kept |

## Costs and privacy, plainly

- **Claude:** comes out of your existing Pro/Max usage limits. Nothing extra.
- **Railway:** about $5/month for light personal use. Check your Railway usage page.
- **Your data** (memories, lists, photos you share, history) lives on your Railway server. Messages go
  to Anthropic to be answered, as they do in the Claude app. Nobody else, including whoever built Camena,
  can see any of it.
