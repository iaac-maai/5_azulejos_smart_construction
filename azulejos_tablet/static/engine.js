// Azulejos brush engine: artisan brushes, in-glaze pigments and the craft steps.
//
// A stroke is painted as a row of "dabs" (stamps of a brush tip) along the
// pencil path. Size follows pressure and tilt, the brush carries a pigment
// load that runs out along the stroke, and finished strokes are multiplied
// onto the raw glaze so overlaps darken and nothing smudges.
// Rendering is deterministic (seeded), so any stroke can be redrawn exactly,
// for undo, for the kiln preview and after a reload.

// ---------- craft steps (used instead of generic layers) ----------
export const STEPS = [
  { id: "estarcido", name: "Estarcido", en: "stencil transfer", note: "charcoal, burns away in the kiln" },
  { id: "perfilado", name: "Perfilado", en: "outline" },
  { id: "relleno", name: "Relleno", en: "fillcd .\azulejos_tablet and wash" },
  { id: "esgrafiado", name: "Esgrafiado", en: "scratched highlights" },
];

// ---------- in-glaze pigments (pintura sobre cubierta) ----------
// raw: how the pigment looks on the unfired, powdery tin glaze
// fired: approximate colour after the glaze firing (~1000 °C)
export const GLAZES = [
  { id: "cobalt", name: "Azul cobalto", en: "cobalt blue", raw: "#5a5d6e", fired: "#1f3f9a" },
  { id: "manganese", name: "Morado de manganeso", en: "manganese purple", raw: "#4d3c35", fired: "#5b2c47" },
  { id: "antimony", name: "Amarillo de antimonio", en: "antimony yellow", raw: "#d6c591", fired: "#e3a21f" },
  { id: "copper", name: "Verde de cobre", en: "copper green", raw: "#545e55", fired: "#3b8b46" },
  { id: "iron", name: "Naranja de hierro", en: "iron orange", raw: "#9c6b4b", fired: "#cf6d1d" },
  { id: "black", name: "Negro", en: "black (Mn + Co + Fe)", raw: "#33302f", fired: "#1d191c" },
];
export const GROUND = { raw: "#e7e0d0", fired: "#f6f2e8", name: "Blanco de estaño", en: "tin-white glaze" };
export const CHARCOAL = "#3a3633";
export const glazeById = Object.fromEntries(GLAZES.map((g) => [g.id, g]));

// ---------- artisan brushes ----------
// size in mm [min, max, default]; spacing as a fraction of the dab diameter;
// capacity in mm² of tile the brush can cover with one dip at full strength;
// pSize/pFlow: how much pressure changes size/strength; tilt: footprint growth
// when the pencil is laid down; aspect: footprint thickness for flat brushes.
export const BRUSHES = [
  {
    id: "munequilla", name: "Muñequilla", en: "pounce bag", step: "estarcido",
    hint: "Charcoal dots, as when pouncing through a trepa (stencil). Guide only: it burns away in the kiln.",
    tip: "dot", size: [0.4, 1.6, 0.8], spacingMm: 1.6, flow: 0.85, capacity: Infinity,
    pSize: 0.2, pFlow: 0.4, tilt: 0, scatter: 0.15, mode: "charcoal",
  },
  {
    id: "perfilador", name: "Perfilador", en: "long liner", step: "perfilado",
    hint: "Long thin hairs for the outlines, usually manganese or cobalt. Pressure makes the line swell.",
    tip: "round", size: [0.3, 4, 1.2], spacing: 0.1, flow: 0.55, capacity: 900,
    pSize: 0.85, pFlow: 0.35, tilt: 0.3, mode: "paint",
  },
  {
    id: "relleno", name: "Pincel de relleno", en: "round fill brush", step: "relleno",
    hint: "Soft round brush that holds plenty of pigment. Lay it down (tilt) for broader marks; colour pools where you lift.",
    tip: "soft", size: [2, 14, 6], spacing: 0.08, flow: 0.2, capacity: 1600,
    pSize: 0.5, pFlow: 0.4, tilt: 0.7, pool: true, mode: "paint",
  },
  {
    id: "paletina", name: "Paletina", en: "flat wash brush", step: "relleno",
    hint: "Wide flat brush for diluted washes (aguadas). The flat edge follows the pencil's direction.",
    tip: "flat", size: [6, 30, 14], spacing: 0.04, flow: 0.07, capacity: 4500,
    pSize: 0.25, pFlow: 0.5, tilt: 0.2, aspect: 0.22, orient: true, pool: true, mode: "paint",
  },
  {
    id: "esponja", name: "Esponja", en: "sponge", step: "relleno",
    hint: "Dab for skies, clouds and marbled backgrounds.",
    tip: "sponge", size: [5, 25, 12], spacing: 0.55, flow: 0.45, capacity: 2600,
    pSize: 0.3, pFlow: 0.6, tilt: 0, jitter: 1, scatter: 0.12, mode: "paint",
  },
  {
    id: "punzon", name: "Punzón", en: "scratching needle", step: "esgrafiado",
    hint: "Scratches pigment away to bring back the white glaze for fine highlights.",
    tip: "round", size: [0.2, 1.6, 0.5], spacing: 0.15, flow: 1, capacity: Infinity,
    pSize: 0.35, pFlow: 0, tilt: 0, mode: "erase",
  },
];
export const brushById = Object.fromEntries(BRUSHES.map((b) => [b.id, b]));

// ---------- seeded randomness ----------
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- brush tips (alpha masks, 4 variants each) ----------
const TIP_PX = 128;
const tips = {};

function makeTip(kind, r) {
  const c = document.createElement("canvas");
  c.width = c.height = TIP_PX;
  const g = c.getContext("2d");
  const m = TIP_PX / 2;
  if (kind === "dot" || kind === "round") {
    const grad = g.createRadialGradient(m, m, 0, m, m, m);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(kind === "dot" ? 0.7 : 0.82, "rgba(255,255,255,0.95)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.beginPath(); g.arc(m, m, m, 0, Math.PI * 2); g.fill();
  } else if (kind === "soft") {
    const grad = g.createRadialGradient(m, m, 0, m, m, m);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.55, "rgba(255,255,255,0.75)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.beginPath(); g.arc(m, m, m, 0, Math.PI * 2); g.fill();
    // goat-hair texture: a few thin, slightly stronger hair marks
    g.globalCompositeOperation = "destination-out";
    for (let i = 0; i < 40; i++) {
      g.fillStyle = `rgba(0,0,0,${0.12 + r() * 0.2})`;
      g.beginPath(); g.arc(m + (r() - 0.5) * TIP_PX * 0.8, m + (r() - 0.5) * TIP_PX * 0.8, 1 + r() * 4, 0, Math.PI * 2); g.fill();
    }
  } else if (kind === "flat") {
    // bristles across the width; each bristle keeps its own strength so the
    // wash shows fine streaks along the stroke
    const h = TIP_PX * 0.22;
    for (let x = 2; x < TIP_PX - 2; x += 1.5) {
      const edge = Math.min(1, Math.min(x, TIP_PX - x) / 10);
      g.fillStyle = `rgba(255,255,255,${(0.35 + r() * 0.65) * edge})`;
      g.fillRect(x, m - h / 2 + r() * 2, 1.4, h - r() * 3);
    }
  } else if (kind === "sponge") {
    // open pores: many small blobs inside a ragged disc
    for (let i = 0; i < 160; i++) {
      const a = r() * Math.PI * 2;
      const d = Math.sqrt(r()) * m * 0.92;
      g.fillStyle = `rgba(255,255,255,${0.25 + r() * 0.75})`;
      g.beginPath(); g.arc(m + Math.cos(a) * d, m + Math.sin(a) * d, 1.5 + r() * 6, 0, Math.PI * 2); g.fill();
    }
  }
  return c;
}

function tipVariants(kind) {
  if (!tips[kind]) {
    const r = rng(kind.length * 7919);
    tips[kind] = [0, 1, 2, 3].map(() => makeTip(kind, r));
  }
  return tips[kind];
}

const tinted = new Map();
function tintedTip(kind, variant, color) {
  const key = `${kind}|${variant}|${color}`;
  let c = tinted.get(key);
  if (!c) {
    const mask = tipVariants(kind)[variant];
    c = document.createElement("canvas");
    c.width = c.height = TIP_PX;
    const g = c.getContext("2d");
    g.drawImage(mask, 0, 0);
    g.globalCompositeOperation = "source-in";
    g.fillStyle = color;
    g.fillRect(0, 0, TIP_PX, TIP_PX);
    tinted.set(key, c);
  }
  return c;
}

// ---------- stroke colour ----------
export function strokeColor(stroke, kiln) {
  const b = brushById[stroke.brush];
  if (b.mode === "charcoal") return CHARCOAL;
  if (b.mode === "erase") return "#000";
  const g = glazeById[stroke.glaze] || GLAZES[0];
  return kiln === "fired" ? g.fired : g.raw;
}

// ---------- the renderer ----------
// Feed it points ({x, y, p, alt, az} in tile mm, y up) one by one; it draws
// dabs onto ctx (canvas px) and keeps the pigment load up to date.
export class StrokeRenderer {
  constructor(stroke, ctx, env) {
    this.s = stroke;
    this.b = brushById[stroke.brush];
    this.ctx = ctx;
    this.k = env.pxPerMm;
    this.tile = env.tileMm;
    this.color = strokeColor(stroke, env.kiln);
    this.rand = rng(stroke.seed);
    this.load = stroke.load_start ?? 1;
    this.prev = null;
    this.until = 0;           // mm along the path until the next dab
    this.ribbon = [];         // [x, y, r] in mm, sampled for Rhino
    this.lastRibbon = null;
  }

  sizeAt(pt) {
    const b = this.b;
    const p = pt.p ?? 0.5;
    const pressure = (1 - b.pSize) + b.pSize * 1.6 * p;
    const lay = 1 - Math.min(1, (pt.alt ?? Math.PI / 2) / (Math.PI / 2));
    return Math.max(0.05, this.s.size_mm * Math.min(1.8, pressure) * (1 + b.tilt * lay));
  }

  spacingAt(d) {
    return this.b.spacingMm || Math.max(0.03, this.b.spacing * d);
  }

  add(pt) {
    if (!this.prev) {
      this.prev = pt;
      this.dab(pt, 0);
      this.until = this.spacingAt(this.sizeAt(pt));
      return;
    }
    const a = this.prev;
    const dx = pt.x - a.x, dy = pt.y - a.y;
    const len = Math.hypot(dx, dy);
    if (len < 1e-6) return;
    const dir = Math.atan2(-dy, dx); // canvas y is down
    while (this.until <= len) {
      const t = this.until / len;
      const q = {
        x: a.x + dx * t, y: a.y + dy * t,
        p: (a.p ?? 0.5) + ((pt.p ?? 0.5) - (a.p ?? 0.5)) * t,
        alt: (a.alt ?? Math.PI / 2) + ((pt.alt ?? Math.PI / 2) - (a.alt ?? Math.PI / 2)) * t,
        az: pt.az ?? 0,
      };
      this.dab(q, dir);
      this.until += this.spacingAt(this.sizeAt(q));
    }
    this.until -= len;
    this.prev = pt;
  }

  finish() {
    // pigment pools a little where a loaded brush lifts off
    if (this.b.pool && this.prev && this.load > 0.25) {
      this.dab({ ...this.prev, p: Math.max(0.3, this.prev.p ?? 0.5) }, 0, 0.6);
    }
    return this.load;
  }

  dab(pt, dir, extra = 1) {
    const b = this.b, r = this.rand;
    const d = this.sizeAt(pt);
    // the brush empties as it covers the tile
    const step = this.spacingAt(d);
    if (Number.isFinite(b.capacity)) this.load = Math.max(0, this.load - (d * step) / b.capacity);
    const load = Number.isFinite(b.capacity) ? this.load : 1;
    // keep the random sequence identical whatever happens below
    const v = Math.floor(r() * 4), skip = r(), jx = r() - 0.5, jy = r() - 0.5, rot = r();
    this.addRibbon(pt, d / 2);
    if (load <= 0) return;
    if (load < 0.3 && skip < ((0.3 - load) / 0.3) * 0.75) return; // dry brush breaks up
    const loadAlpha = load > 0.4 ? 1 : 0.2 + 0.8 * (load / 0.4);
    const p = pt.p ?? 0.5;
    const strength = (1 - b.pFlow) + b.pFlow * Math.min(1, p * 1.5);
    const alpha = Math.min(1, b.flow * strength * loadAlpha * (this.s.dilution ?? 1) * extra);
    if (alpha <= 0.002) return;

    const k = this.k;
    const sc = b.scatter ? b.scatter * d : 0;
    const X = (pt.x + jx * sc) * k;
    const Y = (this.tile - pt.y + jy * sc) * k;
    let angle = 0;
    if (b.orient) angle = (pt.az != null && pt.az !== 0 ? -pt.az : dir) + Math.PI / 2;
    if (b.jitter) angle = rot * Math.PI * 2;
    const w = d * k;
    const ctx = this.ctx;
    ctx.save();
    ctx.translate(X, Y);
    if (angle) ctx.rotate(angle);
    ctx.globalAlpha = alpha;
    ctx.drawImage(tintedTip(b.tip, v, this.color), -w / 2, -w / 2, w, w);
    ctx.restore();
  }

  addRibbon(pt, r) {
    const last = this.lastRibbon;
    if (last && Math.hypot(pt.x - last[0], pt.y - last[1]) < 0.4) return;
    this.lastRibbon = [+pt.x.toFixed(3), +pt.y.toFixed(3), +r.toFixed(3)];
    this.ribbon.push(this.lastRibbon);
  }
}

// ---------- glaze ground ----------
export function makeGround(px, kiln) {
  const c = document.createElement("canvas");
  c.width = c.height = px;
  const g = c.getContext("2d");
  g.fillStyle = GROUND[kiln];
  g.fillRect(0, 0, px, px);
  const r = rng(kiln === "fired" ? 11 : 7);
  if (kiln === "raw") {
    // powdery, matte raw glaze
    for (let i = 0; i < px * 6; i++) {
      g.fillStyle = r() < 0.5 ? "rgba(255,255,255,0.18)" : "rgba(120,105,80,0.07)";
      g.fillRect(r() * px, r() * px, 1 + r() * 2, 1 + r() * 2);
    }
  } else {
    // glossy fired glaze: a soft sheen and a few pinholes
    const sheen = g.createLinearGradient(0, 0, px, px);
    sheen.addColorStop(0, "rgba(255,255,255,0.35)");
    sheen.addColorStop(0.45, "rgba(255,255,255,0)");
    sheen.addColorStop(1, "rgba(160,150,130,0.10)");
    g.fillStyle = sheen;
    g.fillRect(0, 0, px, px);
    for (let i = 0; i < px / 6; i++) {
      g.fillStyle = "rgba(150,140,120,0.25)";
      g.beginPath(); g.arc(r() * px, r() * px, 0.6 + r(), 0, Math.PI * 2); g.fill();
    }
  }
  return c;
}

// small preview of each brush for the brush library
export function brushPreview(brush, glaze, w, h, dpr) {
  const c = document.createElement("canvas");
  c.width = w * dpr; c.height = h * dpr;
  const g = c.getContext("2d");
  const tileMm = 60, k = c.width / tileMm;
  const env = { pxPerMm: k, tileMm: (c.height / k), kiln: "fired" };
  const stroke = {
    brush: brush.id, glaze: glaze.id, size_mm: Math.min(brush.size[2], 9), dilution: 1,
    seed: 4242, load_start: 1,
  };
  if (brush.mode === "erase") {
    g.fillStyle = glazeById.cobalt.fired;
    g.fillRect(0, c.height * 0.25, c.width, c.height * 0.5);
    g.globalCompositeOperation = "destination-out";
  }
  const r = new StrokeRenderer(stroke, g, env);
  const H = env.tileMm;
  for (let i = 0; i <= 60; i++) {
    const t = i / 60;
    r.add({ x: 4 + t * (tileMm - 8), y: H / 2 + Math.sin(t * Math.PI * 2) * H * 0.18, p: 0.25 + 0.6 * Math.sin(t * Math.PI), alt: 1.2, az: 0.6 });
  }
  r.finish();
  return c;
}
