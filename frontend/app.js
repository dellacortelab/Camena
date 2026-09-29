import { renderPet, heartsBurst } from "./pet.js";

const $ = (s) => document.querySelector(s);
const state = { pet: null, activity: null, attachments: [], busy: false, voiceTurn: false, facing: "environment", stream: null };
const prefs = loadPrefs();

// ---------- helpers ----------

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem("camena-prefs") || "{}"); } catch { return {}; }
}
function savePrefs() {
  try { localStorage.setItem("camena-prefs", JSON.stringify(prefs)); } catch { /* private mode */ }
}

async function api(path, opts = {}) {
  const res = await fetch(`api/${path}`, { credentials: "same-origin", ...opts });
  if (res.status === 401 && path !== "login") { showLogin(); throw new Error("locked"); }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}
const post = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
});

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Small, safe markdown: escape first, then add a handful of inline/block rules.
function md(text) {
  const lines = esc(text).split("\n");
  let html = "", inList = false;
  for (const raw of lines) {
    let line = raw
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    const item = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)/);
    if (item) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${item[1]}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    const h = line.match(/^#{1,4}\s+(.*)/);
    if (h) html += `<p><strong>${h[1]}</strong></p>`;
    else if (line.trim()) html += `<p>${line}</p>`;
  }
  if (inList) html += "</ul>";
  return html;
}

function plain(text) {
  return text.replace(/```[\s\S]*?```/g, "").replace(/[*_`#>]/g, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "").trim();
}

// ---------- screens ----------

function showLogin() {
  $("#main").hidden = true;
  $("#login").hidden = false;
  $("#login-pet").innerHTML = renderPet({ stage: "sprout", expression: "sleepy", asleep: true });
  $("#passcode").focus();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await post("login", { passcode: $("#passcode").value });
    $("#passcode").value = "";
    boot();
  } catch (err) {
    $("#login-error").textContent = err.message === "wrong passcode" ? "That's not it." : err.message;
  }
});

async function boot() {
  let s;
  try { s = await api("state"); } catch { return; }
  $("#login").hidden = true;
  state.claude = s.claude;
  if (!s.setup_done) { showSetup(s); return; }
  $("#setup").hidden = true;
  $("#main").hidden = false;
  syncComposer();
  state.vapid = s.vapid_public_key;
  state.owner = s.owner;
  state.pushDevices = s.push_devices;
  setPet(s.pet);
  setUnread(s.unread);
  $("#log").innerHTML = "";
  if (!s.history.length) {
    addBubble("assistant", `Hi ${s.owner}! I'm ${s.pet.name}. Talk to me, show me things with the camera, ` +
      `or ask me to keep an eye on something for you. I remember what matters.`);
  }
  for (const m of s.history) {
    if (m.role === "event") addEvent(m.text);
    else addBubble(m.role, m.text, m.image ? `api/uploads/${m.image}` : null);
  }
  scrollLog();
}

// ---------- first-run setup ----------

const standalone = () => window.navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;

function setupStep(n) {
  [1, 2, 3].forEach((i) => { $(`#step-${i}`).hidden = i !== n; });
  document.querySelectorAll(".steps li").forEach((li) => {
    li.classList.toggle("done", +li.dataset.step < n);
    li.classList.toggle("current", +li.dataset.step === n);
  });
  const moods = { 1: "curious", 2: "thinking", 3: "excited" };
  $("#setup-pet").innerHTML = renderPet({ stage: "sprout", expression: moods[n] });
}

function showSetup(s, step = null) {
  $("#main").hidden = true;
  $("#setup").hidden = false;
  $("#su-name").value = s.owner && s.owner !== "friend" ? s.owner : "";
  $("#su-tz").value = Intl.DateTimeFormat().resolvedOptions().timeZone || s.timezone;
  $("#su-pet").value = s.pet?.name && s.pet.name !== "Cam" ? s.pet.name : "";
  renderClaude(s.claude);
  // After a reload (iOS drops tabs you leave), land where the owner left off.
  setupStep(step ?? (s.owner && s.owner !== "friend" ? 2 : 1));
  if (s.claude?.login_pending && !s.claude?.connected) {
    showCodeEntry();
    setStatus("Welcome back! Paste the code from Claude to finish.");
  }
}

function renderClaude(c) {
  const labels = { subscription: "your Claude subscription", "env-token": "your Claude subscription (server token)",
    "cli-login": "this server's Claude login", "api-key": "an Anthropic API key", "env-api-key": "an API key (server setting)" };
  const box = $("#claude-connected");
  box.hidden = !c?.connected;
  box.textContent = c?.connected ? `✓ Connected via ${labels[c.method] || c.method}${c.model ? ` · ${c.model}` : ""}` : "";
  $("#su-next-2").hidden = !c?.connected;
  $("#su-link").textContent = c?.connected ? "Connect a different account" : "1 · Get my sign-in link";
}

function setStatus(text, busy = false) {
  const el = $("#su-status");
  el.textContent = text;
  el.hidden = !text;
  el.classList.toggle("busy", busy);
  if (text) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function showCodeEntry() {
  ["#su-open", "#su-link-help", "#su-code-form"].forEach((sel) => { $(sel).hidden = false; });
  $("#su-link").hidden = true;
}

function resetCodeEntry(label = "1 · Get my sign-in link") {
  ["#su-open", "#su-link-help", "#su-code-form"].forEach((sel) => { $(sel).hidden = true; });
  $("#su-link").hidden = false;
  $("#su-link").textContent = label;
}

let claudeBusy = false;
async function claudeCall(path, body, button) {
  if (claudeBusy) return;
  claudeBusy = true;
  const label = button?.textContent;
  if (button) { button.disabled = true; button.textContent = "Connecting…"; }
  $("#su-error").textContent = "";
  setStatus("Checking with Claude… this takes up to 20 seconds.", true);
  $("#setup-pet").innerHTML = renderPet({ stage: "sprout", expression: "thinking" }, "thinking");
  try {
    const c = await post(path, body);
    state.claude = c;
    renderClaude(c);
    setStatus("It works. Say hi soon!");
    $("#setup-pet").innerHTML = renderPet({ stage: "sprout", expression: "love" });
    resetCodeEntry("Connect a different account");
  } catch (err) {
    setStatus("");
    $("#su-error").textContent = err.message;
    $("#setup-pet").innerHTML = renderPet({ stage: "sprout", expression: "worried" });
    // After a rejected code the CLI's sign-in session is gone: start over with a fresh link.
    if (path === "claude/login/finish" && !/Already connecting/.test(err.message)) resetCodeEntry("Get a new sign-in link");
  } finally {
    claudeBusy = false;
    if (button) { button.disabled = false; button.textContent = label; }
  }
}

$("#step-1").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#step-1 .error");
  err.textContent = "";
  try {
    await post("setup/profile", { owner_name: $("#su-name").value, timezone: $("#su-tz").value.trim(), pet_name: $("#su-pet").value });
    setupStep(2);
  } catch (ex) { err.textContent = ex.message; }
});

async function getLink() {
  $("#su-error").textContent = "";
  setStatus("Asking Claude for a sign-in link…", true);
  $("#su-link").disabled = true;
  try {
    const { url } = await post("claude/login/start");
    $("#su-open").href = url;
    $("#su-code").value = "";
    showCodeEntry();
    setStatus("");
  } catch (err) {
    setStatus("");
    $("#su-error").textContent = err.message;
  } finally {
    $("#su-link").disabled = false;
  }
}

$("#su-link").addEventListener("click", getLink);
$("#su-restart").addEventListener("click", () => {
  if (confirm("Start over? A code from the previous link will stop working.")) getLink();
});
$("#su-code-form").addEventListener("submit", (e) => { e.preventDefault(); claudeCall("claude/login/finish", { value: $("#su-code").value }, $("#su-connect")); });
$("#su-token-form").addEventListener("submit", (e) => { e.preventDefault(); claudeCall("claude/token", { value: $("#su-token").value }, e.submitter); });
$("#su-key-form").addEventListener("submit", (e) => { e.preventDefault(); claudeCall("claude/api-key", { value: $("#su-key").value }, e.submitter); });
$("#su-next-2").addEventListener("click", () => {
  setupStep(3);
  $("#su-ios").hidden = standalone();
  $("#su-installed").hidden = !standalone();
});
$("#su-finish").addEventListener("click", async () => {
  try { await post("setup/done"); boot(); } catch (err) { alert(err.message); }
});

// ---------- the companion ----------

function setPet(pet) {
  if (!pet) return;
  const evolved = state.pet && state.pet.stage !== pet.stage;
  state.pet = pet;
  $("#pet-name").textContent = pet.name;
  $("#pet-stage").textContent = pet.stage;
  $("#bar-food").style.width = `${100 - pet.hunger}%`;
  $("#bar-energy").style.width = `${pet.energy}%`;
  $("#bar-love").style.width = `${pet.affection}%`;
  drawPet();
  if (pet.thought && !state.activity) think(pet.thought);
  if (evolved) {
    addEvent(`✨ ${pet.name} evolved into a ${pet.stage}!`);
    $("#stage").classList.add("evolve");
    setTimeout(() => $("#stage").classList.remove("evolve"), 1600);
  }
}

function drawPet() {
  $("#pet").innerHTML = renderPet(state.pet, state.activity);
}

function setActivity(activity, label = "") {
  state.activity = activity;
  $("#activity").textContent = label;
  drawPet();
}

let thoughtTimer;
function think(text) {
  const el = $("#thought");
  el.textContent = text;
  el.hidden = !text;
  clearTimeout(thoughtTimer);
  thoughtTimer = setTimeout(() => { el.hidden = true; }, 6000);
}

$("#pet").addEventListener("click", async () => {
  heartsBurst($("#stage"));
  $("#pet").classList.add("squish");
  setTimeout(() => $("#pet").classList.remove("squish"), 400);
  try { setPet(await post("pet/pat")); } catch { /* offline is fine */ }
});

// ---------- chat log ----------

function addBubble(role, text, image = null) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  if (image) div.innerHTML += `<img src="${esc(image)}" alt="Photo you shared" loading="lazy">`;
  const body = document.createElement("div");
  body.className = "text";
  body.innerHTML = role === "assistant" ? md(text) : `<p>${esc(text)}</p>`;
  if (text || role === "assistant") div.appendChild(body);
  $("#log").appendChild(div);
  return body;
}

function addEvent(text) {
  const div = document.createElement("div");
  div.className = "event";
  div.textContent = text;
  $("#log").appendChild(div);
}

function scrollLog() {
  const log = $("#log");
  log.scrollTop = log.scrollHeight;
}

function addApproval(ev) {
  const card = document.createElement("div");
  card.className = "approval";
  card.innerHTML = `<div><strong>Needs your OK:</strong> ${esc(ev.tool.replace(/_/g, " "))}</div>
    <div class="muted small">${esc(ev.summary)}</div>
    <div class="actions"><button class="primary">Approve</button><button class="ghost">Not now</button></div>`;
  const [yes, no] = card.querySelectorAll("button");
  yes.onclick = () => { card.remove(); send("Approved, go ahead.", { approve: true }); };
  no.onclick = () => { card.remove(); send("Don't do that.", {}); };
  $("#log").appendChild(card);
  scrollLog();
}

// ---------- sending ----------

async function send(text, { voice = false, approve = false } = {}) {
  if (state.busy) return;
  const images = state.attachments.splice(0);
  renderAttachments();
  if (!text.trim() && !images.length) return;
  state.busy = true;
  state.voiceTurn = voice;
  unlockSpeech();

  const preview = images[0] ? URL.createObjectURL(images[0]) : null;
  addBubble("user", text || (images.length ? "" : ""), preview);
  const out = addBubble("assistant", "");
  out.parentElement.classList.add("pending");
  scrollLog();
  setActivity("thinking", "thinking…");

  const form = new FormData();
  form.append("text", text);
  form.append("voice", voice ? "true" : "false");
  form.append("approve", approve ? "true" : "false");
  images.forEach((b, i) => form.append("images", b, `photo-${i}.jpg`));

  let reply = "";
  try {
    const res = await api("chat", { method: "POST", body: form });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (!chunk.startsWith("data: ")) continue;
        const ev = JSON.parse(chunk.slice(6));
        if (ev.type === "pet") setPet(ev.pet);
        else if (ev.type === "text") {
          reply += ev.delta;
          out.innerHTML = md(reply);
          out.parentElement.classList.remove("pending");
          if (state.activity !== "speaking") setActivity("thinking", "");
          scrollLog();
        } else if (ev.type === "tool") setActivity("thinking", `${ev.label}…`);
        else if (ev.type === "approval") addApproval(ev);
        else if (ev.type === "error") throw new Error(ev.message);
        else if (ev.type === "done") {
          if (ev.pet) setPet(ev.pet);
          reply = ev.text || reply;
        }
      }
    }
  } catch (err) {
    if (err.message !== "locked") {
      out.innerHTML = `<p class="error">Something went wrong: ${esc(err.message)}</p>`;
    }
  } finally {
    out.parentElement.classList.remove("pending");
    state.busy = false;
    setActivity(null, "");
  }
  if (reply && (voice || prefs.speak)) speak(reply);
}

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#input").value;
  $("#input").value = "";
  syncComposer();
  send(text);
});

$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
});
$("#input").addEventListener("input", syncComposer);

function syncComposer() {
  const el = $("#input");
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  const hasText = el.value.trim().length > 0;
  // Typed text: send. A photo with no text yet: offer both, so you can ask about it out loud.
  $("#send-btn").hidden = !hasText && state.attachments.length === 0;
  $("#mic-btn").hidden = hasText;
}

// ---------- voice ----------

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog = null;

function listen(onFinal) {
  if (!Recognition) {
    $("#input").focus();
    think("Use the keyboard's mic 🎙️");
    return;
  }
  if (recog) { recog.stop(); return; }
  stopSpeaking();
  recog = new Recognition();
  recog.lang = navigator.language || "en-US";
  recog.interimResults = true;
  recog.continuous = false;
  let finalText = "";
  setActivity("listening", "listening…");
  $("#mic-btn").classList.add("live");
  recog.onresult = (e) => {
    let interim = "";
    for (const r of e.results) (r.isFinal ? (finalText = r[0].transcript) : (interim += r[0].transcript));
    $("#activity").textContent = interim || finalText || "listening…";
  };
  recog.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted") think(`mic: ${e.error}`); };
  recog.onend = () => {
    recog = null;
    $("#mic-btn").classList.remove("live");
    setActivity(null, "");
    const text = finalText.trim() || $("#activity").textContent.replace("listening…", "").trim();
    if (text) onFinal(text);
  };
  recog.start();
}

$("#mic-btn").addEventListener("click", () => {
  unlockSpeech(); // must happen inside the tap: the reply is spoken long after it
  listen((t) => send(t, { voice: true }));
});

let speechUnlocked = false;
function unlockSpeech() {
  // iOS only lets speechSynthesis talk after it was used inside a user gesture,
  // and ignores an empty utterance, so speak a silent space.
  if (speechUnlocked || !("speechSynthesis" in window)) return;
  const u = new SpeechSynthesisUtterance(" ");
  u.volume = 0;
  speechSynthesis.speak(u);
  speechUnlocked = true;
}

// Novelty voices macOS/iOS ship that nobody wants reading replies aloud.
const NOVELTY = /albert|bad news|bahh|bells|boing|bubbles|cellos|fred|good news|jester|junior|kathy|organ|ralph|superstar|trinoids|whisper|wobble|zarvox|grandma|grandpa|eddy|flo|reed|rocko|sandy|shelley/i;

let voiceList = [];
function loadVoices() {
  // iOS fills the list asynchronously; the first getVoices() call is often empty.
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve([]);
    const done = () => { voiceList = speechSynthesis.getVoices(); resolve(voiceList); };
    if (speechSynthesis.getVoices().length) return done();
    speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1500);
  });
}

function voiceQuality(v) {
  if (/premium/i.test(v.name)) return 3;
  if (/enhanced|neural|natural/i.test(v.name)) return 2;
  return v.localService === false ? 1.5 : 1;
}

function candidateVoices() {
  const lang = (navigator.language || "en-US").slice(0, 2);
  return voiceList
    .filter((v) => v.lang.startsWith(lang) && !NOVELTY.test(v.name))
    .sort((a, b) => voiceQuality(b) - voiceQuality(a) || (b.lang === navigator.language) - (a.lang === navigator.language));
}

function pickVoice() {
  const chosen = prefs.voice && voiceList.find((v) => v.voiceURI === prefs.voice);
  if (chosen) return chosen;
  const c = candidateVoices();
  return c.find((v) => /ava|zoe|samantha|evan|nathan|allison|susan|serena/i.test(v.name) && voiceQuality(v) >= 2) || c[0] || null;
}

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(plain(text));
  const v = pickVoice();
  if (v) { u.voice = v; u.lang = v.lang; }
  u.rate = 1.0;  // anything else makes even good voices sound synthetic
  u.pitch = 1.0;
  u.onstart = () => setActivity("speaking", "");
  u.onend = u.onerror = () => {
    if (state.activity === "speaking") setActivity(null, "");
    // Conversation mode: after answering a spoken question, listen for the follow-up.
    if (prefs.handsfree && state.voiceTurn && !state.busy && !document.hidden) {
      listen((t) => send(t, { voice: true }));
    }
  };
  speechSynthesis.speak(u);
}

function stopSpeaking() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

// ---------- camera ----------

async function openCamera() {
  $("#camera").hidden = false;
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: state.facing, width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false,
    });
    $("#video").srcObject = state.stream;
  } catch {
    closeCamera();
    $("#file-fallback").click();
  }
}

function closeCamera() {
  state.stream?.getTracks().forEach((t) => t.stop());
  state.stream = null;
  $("#camera").hidden = true;
}

function snap() {
  const video = $("#video");
  if (!video.videoWidth) return null;
  return downscale(video, video.videoWidth, video.videoHeight);
}

// Claude reads images up to ~1568px on the long side; bigger just costs upload time.
function downscale(source, w, h) {
  const scale = Math.min(1, 1568 / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
}

async function attach(blobPromise) {
  const blob = await blobPromise;
  if (!blob) return;
  if (state.attachments.length >= 4) state.attachments.shift();
  state.attachments.push(blob);
  renderAttachments();
  syncComposer();
}

function renderAttachments() {
  const box = $("#attachments");
  box.innerHTML = "";
  box.hidden = state.attachments.length === 0;
  state.attachments.forEach((b, i) => {
    const wrap = document.createElement("div");
    wrap.className = "thumb";
    wrap.innerHTML = `<img src="${URL.createObjectURL(b)}" alt="Attached photo ${i + 1}"><button aria-label="Remove photo">×</button>`;
    wrap.querySelector("button").onclick = () => { state.attachments.splice(i, 1); renderAttachments(); syncComposer(); };
    box.appendChild(wrap);
  });
}

$("#cam-btn").addEventListener("click", openCamera);
$("#cam-close").addEventListener("click", closeCamera);
$("#cam-flip").addEventListener("click", async () => {
  state.facing = state.facing === "environment" ? "user" : "environment";
  closeCamera();
  openCamera();
});
$("#cam-snap").addEventListener("click", async () => {
  $("#camera").classList.add("flash");
  setTimeout(() => $("#camera").classList.remove("flash"), 250);
  await attach(snap());
  closeCamera();
  $("#input").focus();
});
$("#cam-ask").addEventListener("click", async () => {
  unlockSpeech();
  // The Muse Charm move: point, snap, and ask out loud in one tap.
  await attach(snap());
  closeCamera();
  listen((t) => send(t, { voice: true }));
});
$("#file-fallback").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const img = await createImageBitmap(file);
  await attach(downscale(img, img.width, img.height));
  e.target.value = "";
});

// ---------- inbox & drawer ----------

function setUnread(n) {
  $("#unread-dot").hidden = !n;
}

$("#inbox-btn").addEventListener("click", () => openDrawer("inbox"));
$("#menu-btn").addEventListener("click", () => openDrawer("lists"));
$("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") $("#drawer").hidden = true; });
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => openDrawer(b.dataset.tab)));

const localTime = (iso) => iso ? new Date(iso).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";

async function openDrawer(tab) {
  $("#drawer").hidden = false;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
  const body = $("#drawer-body");
  body.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    if (tab === "lists") {
      const lists = await api("lists");
      const names = Object.keys(lists);
      body.innerHTML = names.length ? names.map((n) => `<h3>${esc(n)}</h3><ul class="checklist">${
        lists[n].map((i) => `<li><label><input type="checkbox" data-id="${i.id}"> ${esc(i.text)}</label></li>`).join("")
      }</ul>`).join("") : `<p class="muted">No lists yet. Try “add oat milk to groceries”, or show me a recipe.</p>`;
      body.querySelectorAll("input[type=checkbox]").forEach((c) => c.addEventListener("change", async () => {
        await post(`lists/${c.dataset.id}/done`);
        c.closest("li").classList.add("done");
      }));
    } else if (tab === "agenda") {
      const a = await api("agenda");
      body.innerHTML = `<h3>Reminders</h3>${a.reminders.length ? a.reminders.map((r) =>
        `<div class="card"><div>${esc(r.text)}</div><div class="muted small">${localTime(r.due_at)}</div>
         <button class="ghost small" data-cancel-rem="${r.id}">Cancel</button></div>`).join("")
        : `<p class="muted">None. “Remind me to call mom at 6”.</p>`}
        <h3>Watching for you</h3>${a.tasks.length ? a.tasks.map((t) =>
        `<div class="card"><div><strong>${esc(t.title)}</strong> <span class="badge">${esc(t.schedule)}</span></div>
         <div class="muted small">next ${localTime(t.next_run_at)}${t.last_run_at ? ` · last ${localTime(t.last_run_at)}` : ""}</div>
         ${t.last_result ? `<details><summary class="small">Last result</summary>${md(t.last_result)}</details>` : ""}
         <div class="actions"><button class="ghost small" data-run="${t.id}">Run now</button>
         <button class="ghost small danger" data-cancel-task="${t.id}">Stop</button></div></div>`).join("")
        : `<p class="muted">Nothing yet. “Every morning at 7, check if my flight is delayed and tell me only if it is.”</p>`}`;
      body.querySelectorAll("[data-cancel-rem]").forEach((b) => b.onclick = async () => { await post(`reminders/${b.dataset.cancelRem}/cancel`); openDrawer("agenda"); });
      body.querySelectorAll("[data-cancel-task]").forEach((b) => b.onclick = async () => { await post(`tasks/${b.dataset.cancelTask}/cancel`); openDrawer("agenda"); });
      body.querySelectorAll("[data-run]").forEach((b) => b.onclick = async () => { await post(`tasks/${b.dataset.run}/run`); b.textContent = "Queued"; b.disabled = true; });
    } else if (tab === "memory") {
      const mems = await api("memories");
      body.innerHTML = mems.length ? `<p class="muted small">Everything ${esc(state.pet?.name || "Cam")} knows about you. Tap × to make it forget.</p>` +
        mems.map((m) => `<div class="memory"><span class="badge">${esc(m.topic)}</span> ${esc(m.text)}
          <button class="icon-x" data-forget="${m.id}" aria-label="Forget">×</button></div>`).join("")
        : `<p class="muted">Nothing remembered yet. Tell me about yourself.</p>`;
      body.querySelectorAll("[data-forget]").forEach((b) => b.onclick = async () => {
        await api(`memories/${b.dataset.forget}`, { method: "DELETE" });
        b.parentElement.remove();
      });
    } else if (tab === "inbox") {
      const items = await api("inbox");
      setUnread(0);
      body.innerHTML = items.length ? items.map((i) => `<div class="card ${i.read ? "" : "unread"}">
          <div><strong>${esc(i.title)}</strong> <span class="muted small">${localTime(i.created_at)}</span></div>${md(i.body)}</div>`).join("")
        : `<p class="muted">Quiet. Reminders and background finds land here.</p>`;
    } else if (tab === "activity") {
      const rows = await api("actions");
      body.innerHTML = rows.length ? `<p class="muted small">Every action ${esc(state.pet?.name || "Cam")} took or was stopped from taking.</p>` +
        rows.map((a) => `<div class="action ${a.outcome}"><div><span class="badge">${esc(a.outcome)}</span>
          <strong>${esc(a.tool.replace(/_/g, " "))}</strong> <span class="muted small">${esc(a.source)} · ${localTime(a.created_at)}</span></div>
          <div class="muted small">${esc(a.summary)}</div></div>`).join("")
        : `<p class="muted">Nothing yet.</p>`;
    } else if (tab === "settings") {
      body.innerHTML = $("#settings-tpl").innerHTML;
      $("#set-name").value = state.pet?.name || "";
      $("#set-name").addEventListener("change", async (e) => setPet(await post("pet/name", { name: e.target.value })));
      await loadVoices();
      const voiceSel = $("#set-voice");
      const current = pickVoice();
      voiceSel.innerHTML = candidateVoices().map((v) => {
        const tag = voiceQuality(v) >= 3 ? " (Premium)" : voiceQuality(v) >= 2 ? " (Enhanced)" : "";
        const name = v.name.replace(/\s*\((premium|enhanced)\)/i, "");
        return `<option value="${esc(v.voiceURI)}"${current && v.voiceURI === current.voiceURI ? " selected" : ""}>${esc(name)}${tag} · ${esc(v.lang)}</option>`;
      }).join("") || `<option value="">No voices found</option>`;
      voiceSel.addEventListener("change", () => { prefs.voice = voiceSel.value; savePrefs(); });
      $("#set-voice-test").addEventListener("click", () => {
        unlockSpeech();
        speak(`Hi ${state.owner || ""}, I'm ${state.pet?.name || "Cam"}. How do I sound?`);
      });
      $("#voice-hint").hidden = candidateVoices().some((v) => voiceQuality(v) >= 3);
      $("#set-speak").checked = !!prefs.speak;
      $("#set-speak").addEventListener("change", (e) => { prefs.speak = e.target.checked; savePrefs(); unlockSpeech(); });
      $("#set-handsfree").checked = !!prefs.handsfree;
      $("#set-handsfree").addEventListener("change", (e) => { prefs.handsfree = e.target.checked; savePrefs(); });
      $("#set-brief").addEventListener("click", async () => {
        const r = await post("tasks/morning-brief", { time: $("#set-brief-time").value || "07:00" });
        $("#set-brief").textContent = `Next ${localTime(r.next_run_at)}`;
        $("#set-brief").disabled = true;
      });
      $("#sc-url").textContent = new URL("api/shortcut", location.href).href;
      $("#sc-reveal").addEventListener("click", async () => { $("#sc-token").textContent = (await api("shortcut/token")).token; });
      $("#sc-rotate").addEventListener("click", async () => {
        if (!confirm("Old shortcuts will stop working. Continue?")) return;
        $("#sc-token").textContent = (await post("shortcut/rotate")).token;
      });
      $("#push-status").textContent = pushStatus();
      $("#set-push").addEventListener("click", enablePush);
      $("#set-reset").addEventListener("click", async () => {
        await post("chat/reset");
        $("#drawer").hidden = true;
        addEvent("New conversation");
      });
      $("#set-logout").addEventListener("click", async () => { await post("logout"); showLogin(); });
      const c = state.claude || {};
      $("#claude-status").textContent = c.connected ? `connected (${c.method})` : "not connected";
      $("#set-claude").addEventListener("click", async () => {
        $("#drawer").hidden = true;
        showSetup(await api("state"), 2);
      });
    }
  } catch (err) {
    if (err.message !== "locked") body.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

// ---------- push ----------

function pushStatus() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return window.navigator.standalone === false ? "add to Home Screen first" : "not supported here";
  }
  if (Notification.permission === "denied") return "blocked in Settings";
  return state.pushDevices ? `${state.pushDevices} device(s)` : "off";
}

function urlB64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function enablePush() {
  try {
    if (!("PushManager" in window)) throw new Error("On iPhone: Share → Add to Home Screen, open Camena from there, then try again.");
    const perm = await Notification.requestPermission();
    if (perm !== "granted") throw new Error("Permission not granted.");
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(state.vapid) });
    const r = await post("push/subscribe", sub.toJSON());
    state.pushDevices = r.devices;
    await post("push/test");
    $("#push-status").textContent = pushStatus();
  } catch (err) {
    $("#push-status").textContent = err.message;
  }
}

// ---------- go ----------

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState === "visible" && !$("#main").hidden && !state.busy) {
    try { const s = await api("state"); setPet(s.pet); setUnread(s.unread); } catch { /* ignore */ }
  }
});
syncComposer();
loadVoices();
boot();
