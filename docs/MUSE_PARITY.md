# Camena vs. Meta Muse / Muse Charm

Sources: Meta's [Muse launch post](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/),
[Connect 2026 recap](https://www.meta.com/blog/meta-connect-2026-everything-we-announced/),
[TechCrunch](https://techcrunch.com/2026/09/25/meta-opens-early-access-program-for-new-muse-features/),
[The AI Insider](https://theaiinsider.tech/2026/09/25/meta-goes-all-in-on-muse-ai-agent-at-connect-2026-with-avatars-camera-free-glasses-and-a-keychain-device/),
[Bloomberg](https://www.bloomberg.com/news/articles/2026-09-23/meta-debuts-a-dedicated-palm-sized-muse-charm-device-to-use-ai-on-the-go)
(2026-09-23 → 25). Evaluated 2026-09-28 against Camena `main`; field-tested on an iPhone (Home Screen app, Railway deployment) on 2026-09-29.

**What Muse is.** Muse is Meta's agent (model: Muse Spark), available in its iOS/Android apps, on the web,
in WhatsApp, on a Mac app, and soon on AI glasses. **Muse Charm** is a keychain device made only for
talking to it: a ~2" OLED touchscreen showing an animated avatar ("Jolly"), front and rear cameras, a
fingerprint key that starts listening, and its own 5G. It ships December 2026. Meta hasn't announced a
price; one report says $349.99. Everything the Charm does, an iPhone already does in hardware.

Legend: ✅ parity · 🟡 partial · ❌ gap · ➖ out of scope on purpose

## Scorecard

| # | Muse / Charm feature | Camena | How | Verified |
|---|---|---|---|---|
| 1 | Talk to it by voice | ✅ | Mic button → Web Speech dictation in the Home Screen app; replies spoken with a natural server voice (see #3) | iPhone ✔ |
| 2 | Real-time, interruptible "long conversation" voice mode | 🟡 | *Conversation mode* re-listens after each spoken reply. Turn-based, not full duplex; ~3–7 s per turn | logic only |
| 3 | Custom voice design (speed, accent) | 🟡 | Natural neural voices (Kokoro, 11 American/British voices) generated on your own server and streamed one sentence at a time; the iPhone's own voices are the fallback. Choose a voice, not design one | iPhone ✔ |
| 4 | Squeeze-to-talk key (Charm fingerprint button) | ✅ | iPhone **Action button** → "Ask Camena" Shortcut → `/api/shortcut` → spoken answer | endpoint live-tested (5.2 s) |
| 5 | Wake word ("Hey Muse" on glasses) | ✅ | "Hey Siri, Ask Camena" runs the same Shortcut, from the lock screen and CarPlay | endpoint live-tested |
| 6 | Cameras: identify products, read signs, describe the view | ✅ | Camera sheet (rear/front), **snap-and-ask by voice** in one tap; images go to Claude | live: read a pasta label, cross-checked against memory; iPhone ✔ (Photo, and Snap & ask by voice) |
| 7 | Glasses "sees what you see, no need to describe" | 🟡 | Phone must be pointed; the share sheet sends any photo or screenshot | — |
| 8 | Animated avatar / realtime video avatar | 🟡 | A tamagotchi instead: 4 life stages, 12 expressions the agent sets itself, listening/thinking/talking animations. Not a video avatar | screenshots |
| 9 | Remembers what matters, even things said once | ✅ | `remember` / `recall`; memories go into every session's instructions | live: "vegetarian" used unprompted in a later turn |
| 10 | Tell it to forget | ✅ | Ask it, or tap × in Drawer → Memory | tested |
| 11 | Unprompted suggestions | 🟡 | **Morning briefing** (one tap) suggests things from your memories each day; the pet nudges after 24 h of silence. No always-on event triggers | briefing route tested; nudge tested |
| 12 | Keeps working after you close the app; comes back when something changes | ✅ | Background tasks on a schedule, silent unless their condition is met, then Web Push | live: Lisbon rain check ran, correctly stayed silent; push notifications arrive on iPhone ✔ |
| 13 | Turn goals into a plan and coordinate it | ✅ | Plain Claude + lists + reminders + tasks | — |
| 14 | Recipe reel → grocery list | 🟡 | Share sheet → Camena sends the link or screenshot; Claude builds the list. Instagram pages often need a login, so a **screenshot** is the reliable path | photo path live-tested |
| 15 | Email / calendar / Drive / Notion / GitHub / Box | 🟡 | Whatever you connect in **claude.ai → Connectors** shows up as tools (seen live: Gmail and Calendar are listed but not yet authorized on this account) | connector listing seen; **authorize to test** |
| 16 | 1,500+ connectors | 🟡 | Same claude.ai connector directory; plus any MCP server added to the container | — |
| 17 | Checks with you before sensitive actions | ✅ | Tools that send, create, delete, book or buy are blocked until you tap **Approve**; background runs can never do them | live: postcard tool blocked, then ran once approved |
| 18 | Complete audit trail | ✅ | Drawer → **Activity**: every tool call, its source (chat / Siri / task) and outcome (ran / approved / blocked) | live |
| 19 | Private sandbox ("Secure VM", "Sentinel") | ✅ | Your own container on your own server; no shell or filesystem tools; passcode-locked. Data leaves only for Anthropic | — |
| 20 | Muse's own email address | ❌ | Could be added: a Gmail account connected to Camena only | — |
| 21 | Operates a web browser, fills forms, negotiates | ❌ | Read-only web (search + fetch). Next step: a headless-browser MCP behind the approval gate | — |
| 22 | Mac computer use | ➖ | Use Claude's own desktop app / Claude Code on the Mac | — |
| 23 | Shopping checkout (Link one-time cards, Shop Pay, PayPal, retailer integrations) | ➖ | Deliberately not wired to money. Camena researches and compares, and you buy | — |
| 24 | 1Password credential use | ➖ | Same reason | — |
| 25 | WhatsApp as an interface | ❌ | Not built; Telegram/iMessage bridges are possible later | — |
| 26 | Standalone 5G device, no phone needed | ➖ | The phone is the device | — |
| 27 | Price | ✅ | $0 hardware, runs inside the existing Max plan; server already exists | — |

**Tally (27 rows):** 12 ✅ · 8 🟡 · 3 ❌ · 4 ➖.
If you drop the rows that are out of scope on purpose, **12 of 23 are at parity and 8 more are partial.**
Only three are real gaps: an agent email address, browser form-filling, and WhatsApp.
That's roughly the "95% of what people will actually use it for" in the original question, provided
the iPhone-only items below pass.

## Field test on a real iPhone (2026-09-29)

The first end-to-end run: a fresh Railway account, deploy, set up on the phone, daily use from the Home
Screen app. What it showed, and what was fixed on the spot:

| Area | Result |
|---|---|
| Deploy on Railway (new account, trial credit) | ✔ Online in one build. The only confusion was the dashboard itself |
| Connect Claude from the phone (relayed `claude setup-token`) | ✔ after a fix: real ~100-character codes were typed into the CLI together with Enter, which it swallowed as part of a paste, so the code was never submitted. Enter is now sent separately |
| Connect screen feedback | Fixed: the Connect button shows "Connecting…" and can't be double-tapped, and a sign-in in progress survives Safari reloading the tab |
| Speech recognition in the Home Screen app | ✔ works |
| Camera in the Home Screen app | ✔ works. Added a labelled **Snap & ask** button; the mic stays available when a photo is attached |
| Spoken replies | ✔ after two fixes: speech is now unlocked inside the mic tap (iOS requirement). The phone's own voices sounded robotic, and iOS doesn't give web apps its Premium voices, so replies now use Kokoro on the server |
| Web Push notifications | ✔ arrive after *Enable notifications* in the Home Screen app |
| Camera/mic permission asked again after every screen lock | iOS forgets web-app permissions when it unloads the app. **Fix: iPhone Settings → Apps → Safari → Camera and Microphone → Allow.** Now part of the setup guide |
| Screen auto-locks during long spoken answers | Screen Wake Lock added while listening, thinking or speaking. Awaiting confirmation on the phone |

Still open: claude.ai connectors (Gmail, Calendar) through the phone sign-in. Its token is chat-only
(`user:inference`), so connectors probably won't carry over.

## What would close the remaining gaps

1. **Browser actions** (#21): a Playwright MCP server in the container, with its "click / type / submit"
   tools behind the existing approval gate. Adds ~500 MB of Chromium to the image.
2. **Its own inbox** (#20): a dedicated Gmail account attached through a claude.ai connector, with
   `send` behind approval.
3. **Duplex voice** (#2): a realtime speech model would mean a second vendor and a second bill. Not
   worth it while turn-based voice feels fine.
