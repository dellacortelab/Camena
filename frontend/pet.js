// The companion, drawn as one inline SVG. Stage changes the body, expression
// changes the face, activity (listening / thinking / speaking) overrides both.

const BODY = {
  egg: { rx: 46, ry: 56, cy: 108 },
  sprout: { rx: 50, ry: 46, cy: 116 },
  nymph: { rx: 54, ry: 52, cy: 110 },
  muse: { rx: 56, ry: 54, cy: 108 },
};

function eyes(expr, activity, cx, cy) {
  const L = cx - 18, R = cx + 18;
  const dot = (x, y, r = 7) => `<ellipse class="eye" cx="${x}" cy="${y}" rx="${r}" ry="${r + 1.5}" fill="var(--ink)"/>
    <circle cx="${x + 2.5}" cy="${y - 3}" r="2.3" fill="#fff"/>`;
  if (activity === "listening") return dot(L, cy, 8.5) + dot(R, cy, 8.5);
  if (activity === "thinking") return dot(L + 3, cy - 5, 6) + dot(R + 3, cy - 5, 6);
  switch (expr) {
    case "happy": case "proud":
      return `<path d="M${L - 8} ${cy + 2} q8 -10 16 0 M${R - 8} ${cy + 2} q8 -10 16 0" class="stroke"/>`;
    case "sleepy":
      return `<path d="M${L - 8} ${cy} q8 6 16 0 M${R - 8} ${cy} q8 6 16 0" class="stroke"/>`;
    case "love":
      const heart = (x) => `<path d="M${x} ${cy + 7} l-8 -8 a4.5 4.5 0 0 1 8 -5 a4.5 4.5 0 0 1 8 5 z" fill="var(--heart)"/>`;
      return heart(L) + heart(R);
    case "excited":
      const star = (x) => `<path d="M${x} ${cy - 9} l2.6 6 6.4 .6 -4.9 4.2 1.5 6.3 -5.6 -3.4 -5.6 3.4 1.5 -6.3 -4.9 -4.2 6.4 -.6z" fill="var(--ink)"/>`;
      return star(L) + star(R);
    case "surprised":
      return dot(L, cy, 9) + dot(R, cy, 9);
    case "sad": case "worried":
      return dot(L, cy + 2, 6) + dot(R, cy + 2, 6) +
        `<path d="M${L - 9} ${cy - 9} l14 -4 M${R + 9} ${cy - 9} l-14 -4" class="stroke thin"/>`;
    case "curious":
      return dot(L, cy, 6) + dot(R, cy - 1, 8.5) + `<path d="M${R - 9} ${cy - 16} q9 -6 18 0" class="stroke thin"/>`;
    case "silly":
      return dot(L, cy, 7) + `<path d="M${R - 8} ${cy} l16 0" class="stroke"/>`;
    default:
      return dot(L, cy) + dot(R, cy);
  }
}

function mouth(expr, activity, cx, cy) {
  if (activity === "speaking") return `<ellipse class="talk" cx="${cx}" cy="${cy}" rx="7" ry="5" fill="var(--mouth)"/>`;
  if (activity === "listening") return `<circle cx="${cx}" cy="${cy}" r="3.5" fill="var(--mouth)"/>`;
  switch (expr) {
    case "happy": case "love": case "proud":
      return `<path d="M${cx - 10} ${cy - 3} q10 12 20 0" class="stroke"/>`;
    case "excited":
      return `<path d="M${cx - 11} ${cy - 4} q11 16 22 0 z" fill="var(--mouth)"/>`;
    case "surprised":
      return `<ellipse cx="${cx}" cy="${cy + 1}" rx="6" ry="8" fill="var(--mouth)"/>`;
    case "sad": case "worried":
      return `<path d="M${cx - 8} ${cy + 4} q8 -8 16 0" class="stroke"/>`;
    case "sleepy":
      return `<ellipse cx="${cx}" cy="${cy + 1}" rx="4" ry="3" fill="var(--mouth)"/>`;
    case "silly":
      return `<path d="M${cx - 10} ${cy - 3} q10 10 20 0" class="stroke"/><path d="M${cx - 2} ${cy + 2} q5 10 10 0" fill="var(--heart)"/>`;
    case "thinking": case "curious":
      return `<path d="M${cx - 6} ${cy} l12 -2" class="stroke"/>`;
    default:
      return `<path d="M${cx - 7} ${cy - 1} q7 6 14 0" class="stroke"/>`;
  }
}

function extras(stage, expr, activity, b) {
  let s = "";
  const top = b.cy - b.ry;
  if (stage === "sprout" || stage === "nymph") {
    s += `<path d="M100 ${top + 2} q-2 -16 -16 -22 q16 -2 18 16 q4 -18 20 -16 q-12 8 -20 22" fill="var(--leaf)"/>`;
  }
  if (stage === "muse") {
    s += `<ellipse cx="100" cy="${top - 10}" rx="30" ry="7" fill="none" stroke="var(--halo)" stroke-width="4" class="halo"/>`;
    for (let i = 0; i < 7; i++) {
      const a = Math.PI * (0.15 + 0.7 * (i / 6));
      const x = 100 - Math.cos(a) * 60, y = b.cy - Math.sin(a) * 58;
      s += `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="9" ry="4.5" fill="var(--leaf)"
        transform="rotate(${(-a * 180 / Math.PI + 90).toFixed(0)} ${x.toFixed(1)} ${y.toFixed(1)})"/>`;
    }
  }
  if (stage === "nymph" || stage === "muse") {
    s += `<path d="M${100 - b.rx + 4} ${b.cy + 8} q-16 4 -14 18" class="stroke arm"/>
          <path d="M${100 + b.rx - 4} ${b.cy + 8} q16 4 14 18" class="stroke arm"/>`;
  }
  if (activity === "thinking") {
    s += `<circle class="bubble b1" cx="150" cy="${top + 4}" r="5" fill="var(--bubble)"/>
          <circle class="bubble b2" cx="162" cy="${top - 10}" r="7" fill="var(--bubble)"/>
          <circle class="bubble b3" cx="176" cy="${top - 28}" r="9" fill="var(--bubble)"/>`;
  }
  if (activity === "listening") {
    s += `<path class="wave w1" d="M${100 + b.rx + 12} ${b.cy - 16} q8 16 0 32"/>
          <path class="wave w2" d="M${100 + b.rx + 22} ${b.cy - 24} q12 24 0 48"/>
          <path class="wave w1" d="M${100 - b.rx - 12} ${b.cy - 16} q-8 16 0 32"/>
          <path class="wave w2" d="M${100 - b.rx - 22} ${b.cy - 24} q-12 24 0 48"/>`;
  }
  if (expr === "sleepy" && !activity) {
    s += `<text x="150" y="${top + 6}" class="zzz">z</text><text x="162" y="${top - 10}" class="zzz z2">Z</text>`;
  }
  if ((expr === "sad") && !activity) {
    s += `<path d="M${100 - 22} ${b.cy - 2} q-3 7 0 10 q3 -3 0 -10" fill="var(--tear)"/>`;
  }
  return s;
}

let gradientSeq = 0;

export function renderPet(pet, activity = null) {
  // Unique per render: a gradient inside a hidden SVG does not paint in other SVGs.
  const grad = `bodyGrad${++gradientSeq}`;
  const stage = pet?.stage || "egg";
  const expr = pet?.asleep && !activity ? "sleepy" : (pet?.expression || "neutral");
  const b = BODY[stage] || BODY.sprout;
  const faceY = b.cy - 4;

  if (stage === "egg") {
    const cracks = Math.min(3, Math.floor((pet?.xp || 0) / 2));
    const crack = [
      `<path d="M80 96 l8 8 l6 -8 l8 10" class="stroke thin"/>`,
      `<path d="M112 120 l6 -6 l6 8" class="stroke thin"/>`,
      `<path d="M84 138 l10 -6 l6 6 l8 -4" class="stroke thin"/>`,
    ].slice(0, cracks).join("");
    return `<svg viewBox="0 0 200 180" class="pet-svg egg ${activity || ""}" role="img" aria-label="${pet?.name || "Cam"} (egg)">
      <ellipse cx="100" cy="170" rx="42" ry="6" fill="var(--shadow)"/>
      <g class="body wobble">
        <ellipse cx="100" cy="${b.cy}" rx="${b.rx}" ry="${b.ry}" fill="var(--egg)" stroke="var(--ink)" stroke-width="3"/>
        <circle cx="82" cy="84" r="6" fill="var(--spot)"/><circle cx="120" cy="100" r="8" fill="var(--spot)"/>
        <circle cx="96" cy="140" r="5" fill="var(--spot)"/>${crack}
        ${activity ? `<g class="peek">${eyes("neutral", activity, 100, 112)}</g>` : ""}
      </g></svg>`;
  }

  return `<svg viewBox="0 0 200 180" class="pet-svg ${stage} ${activity || ""} expr-${expr}" role="img"
      aria-label="${pet?.name || "Cam"}, a ${stage}, feeling ${expr}">
    <defs>
      <radialGradient id="${grad}" cx="40%" cy="35%" r="70%">
        <stop offset="0%" style="stop-color: var(--body-hi)"/><stop offset="100%" style="stop-color: var(--body)"/>
      </radialGradient>
    </defs>
    <ellipse cx="100" cy="170" rx="${b.rx - 6}" ry="6" fill="var(--shadow)"/>
    <g class="body bob">
      ${extras(stage, expr, activity, b)}
      <path d="M${100 - b.rx} ${b.cy} a${b.rx} ${b.ry} 0 0 1 ${b.rx * 2} 0
               q0 ${b.ry * 0.9} -${b.rx} ${b.ry} q-${b.rx} ${-b.ry * 0.1} -${b.rx} ${-b.ry}z"
            fill="url(#${grad})" stroke="var(--ink)" stroke-width="3"/>
      <ellipse cx="${100 - 30}" cy="${faceY + 14}" rx="8" ry="5" fill="var(--blush)"/>
      <ellipse cx="${100 + 30}" cy="${faceY + 14}" rx="8" ry="5" fill="var(--blush)"/>
      <g class="face">${eyes(expr, activity, 100, faceY)}${mouth(expr, activity, 100, faceY + 20)}</g>
    </g>
  </svg>`;
}

export function heartsBurst(container) {
  for (let i = 0; i < 5; i++) {
    const h = document.createElement("span");
    h.className = "float-heart";
    h.textContent = "♥";
    h.style.left = `${35 + Math.random() * 30}%`;
    h.style.animationDelay = `${i * 90}ms`;
    container.appendChild(h);
    setTimeout(() => h.remove(), 1600);
  }
}
