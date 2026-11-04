// Azulejos tablet: a painting surface dedicated to in-glaze tile painting.
// Apple Pencil paints; fingers zoom, rotate and undo. Each finished stroke is
// sent to the Mac (server.py), which draws it in Rhino.
import {
  STEPS, GLAZES, BRUSHES, brushById, glazeById, StrokeRenderer, makeGround, brushPreview,
} from "./engine.js";

const $ = (id) => document.getElementById(id);
const RES = 2048;                       // paint resolution of the whole tile, px
const view = $("view");
const vctx = view.getContext("2d");

function layer() {
  const c = document.createElement("canvas");
  c.width = c.height = RES;
  return [c, c.getContext("2d")];
}
const [paint, pctx] = layer();          // fired-on pigment (perfilado + relleno, minus esgrafiado)
const [charcoal, cctx] = layer();       // estarcido: charcoal guide dots
const [buffer, bctx] = layer();         // the stroke being painted right now
const grounds = { raw: makeGround(1024, "raw"), fired: makeGround(1024, "fired") };

const state = {
  tileMm: 150,
  thicknessMm: 12,
  kiln: "raw",
  guides: true,
  brush: "perfilador",
  glaze: "cobalt",
  sizes: Object.fromEntries(BRUSHES.map((b) => [b.id, b.size[2]])),
  dilution: Object.fromEntries(BRUSHES.map((b) => [b.id, 1])),
  loads: Object.fromEntries(BRUSHES.map((b) => [b.id, 1])),   // each brush holds its own pigment
  hidden: new Set(),
  strokes: [],
  redo: [],
  live: null,
  penSeen: false,
  erasing: false,
  eraserMm: 5,
  previewMode: "single",
  selectedCell: "B3",
  placed: {},
  previewCache: new Map(),
};
const k = () => RES / state.tileMm;     // px per mm
const env = () => ({ pxPerMm: k(), tileMm: state.tileMm, kiln: state.kiln });
const brush = () => brushById[state.brush];

// ---------- view (zoom, rotate, pan) ----------
let M = new DOMMatrix();
let fitScale = 1;
let needsDraw = true;
const dirty = () => { needsDraw = true; };

function resize() {
  const r = view.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  view.width = Math.round(r.width * dpr);
  view.height = Math.round(r.height * dpr);
  fit();
}

function fit() {
  const r = view.getBoundingClientRect();
  fitScale = (Math.min(r.width, r.height) * (state.previewMode === "neighbors" ? 0.92 / 3 : 0.88)) / RES;
  M = new DOMMatrix().translate(r.width / 2, r.height / 2).scale(fitScale).translate(-RES / 2, -RES / 2);
  dirty();
}

function toTile(e) {
  const r = view.getBoundingClientRect();
  const p = M.inverse().transformPoint(new DOMPoint(e.clientX - r.left, e.clientY - r.top));
  return { x: p.x / k(), y: state.tileMm - p.y / k() };
}

// ---------- drawing the screen ----------
function drawGuides(ctx) {
  const s = RES;
  ctx.save();
  ctx.strokeStyle = state.kiln === "raw" ? "rgba(70,60,50,.22)" : "rgba(70,60,50,.12)";
  ctx.lineWidth = 1.5 / M.a;
  ctx.setLineDash([10 / M.a, 12 / M.a]);
  ctx.beginPath();
  ctx.moveTo(s / 2, 0); ctx.lineTo(s / 2, s);
  ctx.moveTo(0, s / 2); ctx.lineTo(s, s / 2);
  ctx.moveTo(0, 0); ctx.lineTo(s, s);
  ctx.moveTo(s, 0); ctx.lineTo(0, s);
  ctx.stroke();
  ctx.beginPath(); ctx.arc(s / 2, s / 2, s / 4, 0, Math.PI * 2); ctx.stroke();
  ctx.restore();
}

function draw() {
  if (!needsDraw) return requestAnimationFrame(draw);
  needsDraw = false;
  const dpr = window.devicePixelRatio || 1;
  vctx.setTransform(1, 0, 0, 1, 0, 0);
  vctx.fillStyle = "#1d1a17";
  vctx.fillRect(0, 0, view.width, view.height);
  vctx.setTransform(new DOMMatrix().scale(dpr).multiply(M));
  vctx.imageSmoothingQuality = "high";

  // Neighbor previews are read-only. Draw behind the active centre tile.
  if (state.previewMode === "neighbors") drawNeighbors();

  // the tile body and its glaze
  vctx.save();
  vctx.shadowColor = "rgba(0,0,0,.55)";
  vctx.shadowBlur = 40 * M.a * dpr;
  vctx.shadowOffsetY = 18 * M.a * dpr;
  vctx.fillStyle = "#c9b79b";
  vctx.fillRect(0, 0, RES, RES);
  vctx.restore();
  vctx.drawImage(grounds[state.kiln], 0, 0, RES, RES);

  // pigment soaks into the glaze: multiply, so overlaps darken
  vctx.globalCompositeOperation = "multiply";
  vctx.drawImage(paint, 0, 0);
  if (state.live && !state.live.eraser && brush().mode === "paint") vctx.drawImage(buffer, 0, 0);
  vctx.globalCompositeOperation = "source-over";

  if (state.kiln === "fired") {
    // the melted glaze adds a gloss over everything
    const g = vctx.createLinearGradient(0, 0, RES, RES);
    g.addColorStop(0, "rgba(255,255,255,.16)");
    g.addColorStop(0.4, "rgba(255,255,255,0)");
    vctx.fillStyle = g;
    vctx.fillRect(0, 0, RES, RES);
  } else if (!state.hidden.has("estarcido")) {
    vctx.drawImage(charcoal, 0, 0);   // charcoal burns away in the kiln
  }
  if (state.guides) drawGuides(vctx);
  vctx.strokeStyle = "rgba(0,0,0,.25)";
  vctx.lineWidth = 1 / M.a;
  vctx.strokeRect(0, 0, RES, RES);
  requestAnimationFrame(draw);
}

// ---------- 3 × 3 read-only façade context ----------
function adjacentCell(dr, dc) {
  const row = "ABCDE".indexOf(state.selectedCell[0]) + dr;
  const col = Number(state.selectedCell[1]) + dc;
  return row >= 0 && row < 5 && col >= 1 && col <= 6 ? "ABCDE"[row] + col : null;
}

function previewCanvas(cell) {
  if (state.previewCache.has(cell)) return state.previewCache.get(cell);
  const entry = state.placed[cell];
  if (!entry || !Array.isArray(entry.strokes) || !entry.strokes.length) return null;
  const [ink, inkctx] = layer();
  const [dust, dustctx] = layer();
  const [tmp, tmpctx] = layer();
  const scale = RES / (entry.tile_mm || 150);
  const renderEnv = { pxPerMm: scale, tileMm: entry.tile_mm || 150, kiln: state.kiln };
  for (const s of entry.strokes) {
    const b = brushById[s.brush];
    if (!b) continue;
    const target = b.mode === "charcoal" ? dustctx : b.mode === "erase" ? inkctx : tmpctx;
    if (b.mode === "paint") tmpctx.clearRect(0, 0, RES, RES);
    if (b.mode === "erase") target.globalCompositeOperation = "destination-out";
    const r = new StrokeRenderer(s, target, renderEnv);
    for (const pt of s.points || []) r.add(pt);
    r.finish();
    target.globalCompositeOperation = "source-over";
    if (b.mode === "paint") {
      inkctx.globalCompositeOperation = "multiply";
      inkctx.drawImage(tmp, 0, 0);
      inkctx.globalCompositeOperation = "source-over";
    }
  }
  const [result, ctx] = layer();
  ctx.drawImage(grounds[state.kiln], 0, 0, RES, RES);
  ctx.globalCompositeOperation = "multiply";
  ctx.drawImage(ink, 0, 0);
  ctx.globalCompositeOperation = "source-over";
  if (state.kiln === "raw") ctx.drawImage(dust, 0, 0);
  state.previewCache.set(cell, result);
  return result;
}

function drawNeighbors() {
  vctx.save();
  for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
    if (!dr && !dc) continue;
    const x = dc * RES, y = dr * RES;
    const cell = adjacentCell(dr, dc);
    vctx.fillStyle = "#514b43";
    vctx.fillRect(x, y, RES, RES);
    if (cell) {
      const preview = previewCanvas(cell);
      if (preview) vctx.drawImage(preview, x, y, RES, RES);
      else {
        vctx.fillStyle = "#e6dfd0";
        vctx.fillRect(x, y, RES, RES);
        vctx.fillStyle = "#887c6c";
        vctx.font = "48px sans-serif";
        vctx.fillText("No saved preview", x + 50, y + RES / 2);
      }
    } else {
      vctx.fillStyle = "#26221f";
      vctx.fillRect(x, y, RES, RES);
    }
    vctx.strokeStyle = "#887a66";
    vctx.lineWidth = 3;
    vctx.strokeRect(x, y, RES, RES);
    vctx.fillStyle = cell ? "#2e2924" : "#665f55";
    vctx.fillRect(x + 30, y + 30, 240, 100);
    vctx.fillStyle = "#fff";
    vctx.font = "bold 72px sans-serif";
    vctx.fillText(cell || "Outside", x + 45, y + 105);
  }
  vctx.restore();
}

async function refreshPreviews() {
  try {
    const r = await (await fetch("/api/facade-previews", { cache: "no-store" })).json();
    const incoming = r.cells || {};
    if (JSON.stringify(incoming) !== JSON.stringify(state.placed)) {
      state.placed = incoming;
      state.previewCache.clear();
      dirty();
    }
  } catch (err) { console.warn("Façade preview unavailable", err); }
}

// ---------- strokes ----------
function paintStroke(s) {
  if (state.hidden.has(s.step)) return null;
  const b = brushById[s.brush];
  let r;
  if (b.mode === "paint") {
    bctx.clearRect(0, 0, RES, RES);
    r = new StrokeRenderer(s, bctx, env());
    for (const p of s.points) r.add(p);
    r.finish();
    pctx.globalCompositeOperation = "multiply";
    pctx.drawImage(buffer, 0, 0);
    pctx.globalCompositeOperation = "source-over";
    bctx.clearRect(0, 0, RES, RES);
  } else {
    const ctx = b.mode === "erase" ? pctx : cctx;
    if (b.mode === "erase") ctx.globalCompositeOperation = "destination-out";
    r = new StrokeRenderer(s, ctx, env());
    for (const p of s.points) r.add(p);
    r.finish();
    ctx.globalCompositeOperation = "source-over";
  }
  return r;
}

function rebuild() {
  pctx.clearRect(0, 0, RES, RES);
  cctx.clearRect(0, 0, RES, RES);
  for (const s of state.strokes) paintStroke(s);
  updateSteps();
  dirty();
}

function angles(e) {
  if (e.pointerType === "pen" && typeof e.altitudeAngle === "number") return [e.altitudeAngle, e.azimuthAngle || 0];
  const tx = Math.tan(((e.tiltX || 0) * Math.PI) / 180);
  const ty = Math.tan(((e.tiltY || 0) * Math.PI) / 180);
  if (!tx && !ty) return [Math.PI / 2, 0];
  return [Math.atan(1 / Math.hypot(tx, ty)), Math.atan2(ty, tx)];
}

function sample(e, t0) {
  const { x, y } = toTile(e);
  const [alt, az] = angles(e);
  const p = e.pointerType === "pen" ? e.pressure : 0.5;
  return {
    t: +(e.timeStamp - t0).toFixed(1), x: +x.toFixed(3), y: +y.toFixed(3),
    p: +p.toFixed(4), alt: +alt.toFixed(4), az: +az.toFixed(4),
  };
}

function startStroke(e) {
  if (state.erasing) {
    const t0 = e.timeStamp;
    state.live = { eraser: true, pointerId: e.pointerId, t0, points: [] };
    addPoint(e);
    return;
  }
  const b = brush();
  const glaze = b.mode === "paint" ? state.glaze : b.mode === "erase" ? "white" : "charcoal";
  const s = {
    step: b.step, brush: b.id, glaze,
    size_mm: state.sizes[b.id], dilution: state.dilution[b.id],
    load_start: state.loads[b.id], seed: (Math.random() * 2 ** 31) >>> 0,
    device: e.pointerType, started: Date.now(), points: [],
  };
  if (state.hidden.has(s.step)) {
    state.hidden.delete(s.step);   // painting on a hidden step shows it again
    rebuild();
  }
  let ctx = bctx;
  if (b.mode === "erase") { ctx = pctx; pctx.globalCompositeOperation = "destination-out"; }
  if (b.mode === "charcoal") ctx = cctx;
  bctx.clearRect(0, 0, RES, RES);
  const t0 = e.timeStamp;
  state.live = { s, r: new StrokeRenderer(s, ctx, env()), pointerId: e.pointerId, t0 };
  addPoint(e);
}

function addPoint(e) {
  const live = state.live;
  const pt = sample(e, live.t0);
  if (live.eraser) { live.points.push(pt); return; }
  live.s.points.push(pt);
  live.r.add(pt);
  dirty();
}

function endStroke() {
  if (state.live.eraser) {
    const path = state.live.points;
    state.live = null;
    if (path.length) queue(async () => {
      const result = await post("/api/erase", { points: path, radius_mm: state.eraserMm / 2 });
      if (result.error) throw new Error(result.error);
      state.strokes = result.strokes.map(upgrade); state.redo = []; rebuild();
      toast("Erased sketch segments");
      return result;
    });
    return;
  }
  const { s, r } = state.live;
  state.live = null;
  const b = brushById[s.brush];
  state.loads[b.id] = r.finish();
  if (b.mode === "paint") {
    pctx.globalCompositeOperation = "multiply";
    pctx.drawImage(buffer, 0, 0);
    bctx.clearRect(0, 0, RES, RES);
  }
  pctx.globalCompositeOperation = "source-over";
  s.ribbon = r.ribbon;
  state.strokes.push(s);
  state.redo = [];
  updateLoad();
  updateSteps();
  dirty();
  send(s);
}

function cancelStroke() {
  state.live = null;
  pctx.globalCompositeOperation = "source-over";
  bctx.clearRect(0, 0, RES, RES);
  rebuild();
}

function undo() {
  const s = state.strokes.pop();
  if (!s) return toast("Nothing to undo");
  state.redo.push(s);
  state.loads[s.brush] = s.load_start;
  rebuild();
  updateLoad();
  toast("Undo");
  queue(() => post("/api/undo", {}));
}

function redo() {
  const s = state.redo.pop();
  if (!s) return toast("Nothing to redo");
  state.strokes.push(s);
  rebuild();
  toast("Redo");
  send(s);
}

// ---------- pencil and finger input ----------
const touches = new Map();
let gesture = null;

function startGesture() {
  gesture = {
    M0: M, P0: new Map([...touches].map(([id, p]) => [id, { ...p }])),
    t0: performance.now(), moved: gesture?.moved || false,
    max: Math.max(gesture?.max || 0, touches.size),
  };
}

function updateGesture() {
  const ids = [...gesture.P0.keys()].filter((id) => touches.has(id));
  for (const id of ids) {
    const a = gesture.P0.get(id), b = touches.get(id);
    if (Math.hypot(b.x - a.x, b.y - a.y) > 10) gesture.moved = true;
  }
  if (!gesture.moved) return;
  const r = view.getBoundingClientRect();
  const local = (p) => ({ x: p.x - r.left, y: p.y - r.top });
  if (ids.length >= 2) {
    const a0 = local(gesture.P0.get(ids[0])), b0 = local(gesture.P0.get(ids[1]));
    const a1 = local(touches.get(ids[0])), b1 = local(touches.get(ids[1]));
    const d0 = Math.hypot(b0.x - a0.x, b0.y - a0.y), d1 = Math.hypot(b1.x - a1.x, b1.y - a1.y);
    let s = d1 / Math.max(d0, 1);
    const total = gesture.M0.a ? Math.hypot(gesture.M0.a, gesture.M0.b) * s : s;
    s *= Math.min(1, (fitScale * 10) / total) * Math.max(1, (fitScale * 0.4) / total);
    const ang = (Math.atan2(b1.y - a1.y, b1.x - a1.x) - Math.atan2(b0.y - a0.y, b0.x - a0.x)) * 180 / Math.PI;
    const m0 = { x: (a0.x + b0.x) / 2, y: (a0.y + b0.y) / 2 }, m1 = { x: (a1.x + b1.x) / 2, y: (a1.y + b1.y) / 2 };
    M = new DOMMatrix().translate(m1.x, m1.y).rotate(ang).scale(s).translate(-m0.x, -m0.y).multiply(gesture.M0);
  } else if (ids.length === 1) {
    const a0 = gesture.P0.get(ids[0]), a1 = touches.get(ids[0]);
    M = new DOMMatrix().translate(a1.x - a0.x, a1.y - a0.y).multiply(gesture.M0);
  }
  dirty();
}

view.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  view.setPointerCapture(e.pointerId);
  if (e.pointerType === "touch") {
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (state.live && !state.live.eraser && state.live.s.device === "touch") cancelStroke();
    if (touches.size >= 2 || state.penSeen) { startGesture(); return; }
  } else if (e.pointerType === "pen") {
    const q = toTile(e);
    if (q.x < 0 || q.x > state.tileMm || q.y < 0 || q.y > state.tileMm) return;
    state.penSeen = true;
  }
  if (gesture || state.live) return;
  const hit = toTile(e);
  if (hit.x < 0 || hit.x > state.tileMm || hit.y < 0 || hit.y > state.tileMm) return;
  startStroke(e);
});

view.addEventListener("pointermove", (e) => {
  if (e.pointerType === "touch" && touches.has(e.pointerId)) {
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (gesture) return updateGesture();
  }
  const live = state.live;
  if (!live || e.pointerId !== live.pointerId) return;
  const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
  for (const ev of events.length ? events : [e]) addPoint(ev);
});

function pointerEnd(e) {
  if (e.pointerType === "touch") {
    touches.delete(e.pointerId);
    if (gesture) {
      if (touches.size === 0) {
        const quick = performance.now() - gesture.t0 < 350;
        if (!gesture.moved && quick && gesture.max === 2) undo();
        if (!gesture.moved && quick && gesture.max >= 3) redo();
        gesture = null;
      } else {
        startGesture();   // a finger lifted: continue from here
      }
      return;
    }
  }
  if (state.live && e.pointerId === state.live.pointerId) {
    if (e.type === "pointercancel" && !state.live.eraser && state.live.s.points.length < 3) cancelStroke();
    else endStroke();
  }
}
view.addEventListener("pointerup", pointerEnd);
view.addEventListener("pointercancel", pointerEnd);
view.addEventListener("wheel", (e) => {   // trackpad / mouse zoom when testing on the Mac
  e.preventDefault();
  const r = view.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;
  const s = Math.exp(-e.deltaY * 0.002);
  M = new DOMMatrix().translate(x, y).scale(s).translate(-x, -y).multiply(M);
  dirty();
}, { passive: false });
document.addEventListener("gesturestart", (e) => e.preventDefault());

// ---------- side sliders ----------
function vslider(el, get, set, format) {
  const track = el.querySelector(".track");
  const show = () => {
    const v = get();
    const h = track.clientHeight - 22;
    el.querySelector(".thumb").style.bottom = `${v * h}px`;
    el.querySelector(".fill").style.height = `${v * h + 11}px`;
    el.querySelector("output").textContent = format();
  };
  const move = (e) => {
    const r = track.getBoundingClientRect();
    set(Math.min(1, Math.max(0, 1 - (e.clientY - r.top - 11) / (r.height - 22))));
    show();
  };
  track.addEventListener("pointerdown", (e) => { track.setPointerCapture(e.pointerId); move(e); });
  track.addEventListener("pointermove", (e) => { if (e.buttons || e.pressure) move(e); });
  return show;
}

// size slider is logarithmic between the brush's min and max
const sizeShow = vslider($("sizeSlider"),
  () => { const [a, b] = brush().size; return Math.log(state.sizes[state.brush] / a) / Math.log(b / a); },
  (v) => { const [a, b] = brush().size; state.sizes[state.brush] = +(a * (b / a) ** v).toFixed(2); },
  () => `${state.sizes[state.brush].toFixed(state.sizes[state.brush] < 2 ? 1 : 0)} mm`);
const dilShow = vslider($("dilSlider"),
  () => (state.dilution[state.brush] - 0.1) / 0.9,
  (v) => { state.dilution[state.brush] = +(0.1 + 0.9 * v).toFixed(2); },
  () => `${Math.round(state.dilution[state.brush] * 100)}%`);

function updateLoad() {
  const b = brush();
  const finite = Number.isFinite(b.capacity);
  const load = finite ? state.loads[b.id] : 1;
  const el = $("load");
  el.querySelector(".level").style.height = `${load * 100}%`;
  el.querySelector(".level").style.background =
    b.mode === "paint" ? glazeById[state.glaze][state.kiln] : b.mode === "charcoal" ? "#555" : "transparent";
  el.classList.toggle("empty", finite && load < 0.08);
  el.style.visibility = finite ? "visible" : "hidden";
}

function dip() {
  state.loads[state.brush] = 1;
  updateLoad();
  toast(`Brush dipped in ${glazeById[state.glaze].name.toLowerCase()}`);
}
$("load").onclick = dip;

// ---------- panel ----------
function buildBrushes() {
  const dpr = window.devicePixelRatio || 1;
  const box = $("brushes");
  box.innerHTML = "";
  for (const b of BRUSHES) {
    const btn = document.createElement("button");
    btn.className = "brush";
    btn.dataset.id = b.id;
    btn.appendChild(brushPreview(b, glazeById.cobalt, 96, 38, dpr));
    btn.insertAdjacentHTML("beforeend", `<span><b>${b.name}</b><small>${b.en}</small></span>`);
    btn.onclick = () => selectBrush(b.id);
    box.appendChild(btn);
  }
}

function selectBrush(id) {
  state.erasing = false;
  $("eraserTool")?.classList.remove("on");
  state.brush = id;
  const b = brush();
  for (const el of $("brushes").children) el.classList.toggle("on", el.dataset.id === id);
  $("brushHint").textContent = b.hint;
  $("glazes").classList.toggle("disabled", b.mode !== "paint");
  sizeShow(); dilShow(); updateLoad(); updateSteps();
}

function buildGlazes() {
  const box = $("glazes");
  box.innerHTML = "";
  for (const g of GLAZES) {
    const btn = document.createElement("button");
    btn.className = "glaze";
    btn.dataset.id = g.id;
    btn.innerHTML = `<span class="swatch"></span>${g.en.split(" (")[0]}`;
    btn.onclick = () => {
      if (state.glaze !== g.id) state.glaze = g.id;
      paintGlazes();
      dip();
    };
    box.appendChild(btn);
  }
  paintGlazes();
}

function paintGlazes() {
  const other = state.kiln === "raw" ? "fired" : "raw";
  for (const el of $("glazes").children) {
    const g = glazeById[el.dataset.id];
    el.style.setProperty("--c", g[state.kiln]);
    el.style.setProperty("--c2", g[other]);
    el.classList.toggle("on", g.id === state.glaze);
  }
  const g = glazeById[state.glaze];
  $("glazeName").textContent = `${g.name} — the small dot shows it ${other === "fired" ? "after firing" : "raw"}.`;
}

const EYE = '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
function buildSteps() {
  const box = $("steps");
  box.innerHTML = "";
  for (const st of STEPS) {
    const row = document.createElement("div");
    row.className = "step";
    row.dataset.id = st.id;
    row.innerHTML = `<button class="eye" aria-label="Show or hide ${st.name}">${EYE}</button>
      <span><b>${st.name}</b><small>${st.en}${st.note ? " · " + st.note : ""}</small></span><span class="n"></span>`;
    row.querySelector(".eye").onclick = () => {
      if (state.hidden.has(st.id)) state.hidden.delete(st.id); else state.hidden.add(st.id);
      rebuild();
    };
    box.appendChild(row);
  }
}

function updateSteps() {
  for (const row of $("steps").children) {
    const id = row.dataset.id;
    row.classList.toggle("active", brush().step === id);
    row.classList.toggle("hidden", state.hidden.has(id));
    row.querySelector(".n").textContent = state.strokes.filter((s) => s.step === id).length || "";
  }
}

// ---------- top bar ----------
$("kiln").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b || b.dataset.v === state.kiln) return;
  state.kiln = b.dataset.v;
  for (const x of $("kiln").children) x.classList.toggle("on", x === b);
  state.previewCache.clear();
  paintGlazes(); updateLoad(); rebuild();
  toast(state.kiln === "fired" ? "Kiln preview: colours after firing, charcoal burnt away" : "Raw glaze: what the painter sees");
});
$("undo").onclick = undo;
$("redo").onclick = redo;
$("fit").onclick = fit;
$("eraserTool").onclick = () => {
  state.erasing = !state.erasing;
  $("eraserTool").classList.toggle("on", state.erasing);
  toast(state.erasing ? "Eraser selected" : "Brush selected");
};
$("eraserSize").oninput = (e) => {
  state.eraserMm = Number(e.target.value);
  $("eraserValue").textContent = state.eraserMm + " mm";
};
$("clearSketch").onclick = () => {
  if (!confirm("Clear the current sketch? Placed façade cells will be kept.")) return;
  queue(async () => {
    try {
      const result = await post("/api/clear", {});
      if (result.error) throw new Error(result.error);
      state.strokes = []; state.redo = [];
      rebuild();
      toast("Working sketch cleared in Rhino; façade preserved");
      return result;
    } catch (err) {
      toast("Could not clear Rhino: " + err.message);
      throw err;
    }
  });
};

function tileLabel() {
  $("tileBtn").textContent = `${state.tileMm} × ${state.tileMm} × ${state.thicknessMm} mm`;
}
$("tileBtn").onclick = (e) => { e.stopPropagation(); $("tilePop").hidden = !$("tilePop").hidden; };
document.addEventListener("pointerdown", (e) => {
  if (!$("tilePop").hidden && !e.target.closest("#tilePop, #tileBtn")) $("tilePop").hidden = true;
});
$("guides").onchange = (e) => { state.guides = e.target.checked; dirty(); };
$("thickness").onchange = (e) => {
  state.thicknessMm = Number(e.target.value);
  tileLabel();
  queue(() => post("/api/thickness", { thickness_mm: state.thicknessMm }));
};
$("newTile").onclick = () => {
  const tile = Number($("tileSide").value);
  const clear = state.strokes.length ? confirm("Start a new tile? OK also removes this painting from Rhino.") : true;
  state.tileMm = tile;
  state.strokes = []; state.redo = [];
  for (const id in state.loads) state.loads[id] = 1;
  tileLabel(); rebuild(); fit(); updateLoad();
  $("tilePop").hidden = true;
  queue(() => post("/api/new", { tile_mm: tile, thickness_mm: state.thicknessMm, clear_rhino: clear }));
};

let toastTimer;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 1400);
}

// ---------- server ----------
let chain = Promise.resolve();
function queue(fn) {
  chain = chain.then(fn).then((r) => {
    if (r && "rhino" in r) setRhino(r.rhino);
    return r;
  }).catch(() => setRhino(null));
  return chain;
}

async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return res.json();
}

function setRhino(up) {
  const el = $("rhino");
  el.className = "status " + (up ? "up" : "down");
  el.querySelector("span").textContent = up ? "Rhino" : up === null ? "Mac offline" : "Rhino offline";
}

function send(s) {
  const body = {
    step: s.step, brush: s.brush, glaze: s.glaze, size_mm: s.size_mm, dilution: s.dilution,
    load_start: s.load_start, seed: s.seed, device: s.device, started: s.started,
    points: s.points, ribbon: s.ribbon,
  };
  queue(() => post("/api/stroke", body));
}

// strokes saved by earlier versions of the app had a role and pigment only
function upgrade(s) {
  const brushId = s.brush || (s.role === "relleno" ? "relleno" : "perfilador");
  return {
    ...s,
    brush: brushId,
    step: s.step || brushById[brushId].step,
    glaze: s.glaze || s.pigment || "cobalt",
    size_mm: s.size_mm ?? s.tool?.size_mm ?? 2,
    dilution: s.dilution ?? 1,
    load_start: s.load_start ?? 1,
    seed: s.seed ?? (s.id || 1) * 7919,
    device: s.device || s.tool?.device || "pen",
  };
}


// Manual facade placement. The working sketch stays live; publishing copies it.
function buildFacadeSelector() {
  const panel = document.createElement("section");
  panel.id = "facadePanel";
  panel.innerHTML = '<div style="font-weight:700;margin-bottom:8px">Façade destination</div><div id="facadeCells" style="display:grid;grid-template-columns:repeat(6,1fr);gap:4px"></div><div style="margin-top:8px">Selected: <strong id="facadeSelected">B3</strong></div><button id="facadeSend" style="width:100%;margin-top:8px;padding:10px;background:#e7c994;color:#211b15;border:0;border-radius:5px;font-weight:700">Send sketch to B3</button><button id="facadeDelete" type="button" style="width:100%;margin-top:6px;padding:8px;background:transparent;color:#e7c994;border:1px solid #766b5e;border-radius:5px">Remove tile from B3</button><p style="font-size:11px;opacity:.8">Editing or erasing the working sketch does not change a placed cell until you press Send again.</p><div id="facadeMessage" style="font-size:12px;margin-top:6px;min-height:16px"></div>';
  $("panel").appendChild(panel);
  let selected = state.selectedCell;
  const modeWrap = document.createElement("div");
  modeWrap.className = "facade-view-mode";
  modeWrap.innerHTML = '<div style="font-weight:700;margin-bottom:6px">Canvas view</div><div style="display:flex;gap:6px"><button type="button" data-mode="single">Single tile</button><button type="button" data-mode="neighbors">Centre + 8</button></div><p style="font-size:11px;opacity:.8">Only the centre tile is editable. Surrounding cells show saved Send snapshots.</p>';
  panel.prepend(modeWrap);
  function setMode(mode) {
    state.previewMode = mode;
    for (const b of modeWrap.querySelectorAll("button")) {
      b.style.background = b.dataset.mode === mode ? "#3469aa" : "#40392f";
    }
    fit();
  }
  for (const b of modeWrap.querySelectorAll("button")) {
    b.style.cssText = "flex:1;padding:8px 3px;border:1px solid #766b5e;border-radius:5px;color:#fff;font-size:12px";
    b.onclick = () => setMode(b.dataset.mode);
  }
  setMode("single");
  const cells = panel.querySelector("#facadeCells");
  for (const row of "ABCDE") for (let col = 1; col <= 6; col++) {
    const id = row + col;
    const b = document.createElement("button");
    b.textContent = id;
    b.type = "button";
    b.style.cssText = "padding:7px 3px;border:1px solid #766b5e;border-radius:4px;color:#fff;background:#40392f;font-size:12px";
    b.onclick = () => {
      selected = id;
      state.selectedCell = id;
      dirty();
      panel.querySelector("#facadeSelected").textContent = id;
      panel.querySelector("#facadeSend").textContent = "Send sketch to " + id;
      panel.querySelector("#facadeDelete").textContent = "Remove tile from " + id;
      for (const child of cells.children) child.style.background = child.textContent === id ? "#3469aa" : "#40392f";
    };
    cells.appendChild(b);
    if (id === selected) b.style.background = "#3469aa";
  }
  panel.querySelector("#facadeDelete").onclick = async () => {
    const cell = selected;
    if (!confirm("Remove the placed tile from " + cell + " in Rhino? The grid and iPad sketch will remain.")) return;
    const btn = panel.querySelector("#facadeDelete");
    const msg = panel.querySelector("#facadeMessage");
    btn.disabled = true;
    try {
      await chain;
      const response = await post("/api/delete-cell", { cell });
      if (!response.ok) throw new Error(response.error || "Deletion failed");
      msg.textContent = "Removed placed tile from " + cell + " ✓";
      await refreshPreviews();
      if (!state.placed[selected]?.strokes?.length) msg.textContent = "Placed, but preview snapshot missing — check server.";
    } catch (err) { msg.textContent = "Error: " + err.message; }
    finally { btn.disabled = false; }
  };
  panel.querySelector("#facadeSend").onclick = async () => {
    const btn = panel.querySelector("#facadeSend");
    const msg = panel.querySelector("#facadeMessage");
    if (!state.strokes.length) { msg.textContent = "Draw something first."; return; }
    btn.disabled = true;
    msg.textContent = "Sending…";
    try {
      // Wait for all live strokes to reach Rhino before copying the geometry.
      await chain;
      const response = await post("/api/place", { cell: selected });
      if (!response.ok) throw new Error(response.error || "Placement failed");
      msg.textContent = (response.result.replaced ? "Replaced previous tile in " : "Placed in ") + selected + " ✓";
      await refreshPreviews();
      if (!state.placed[selected]?.strokes?.length) msg.textContent = "Placed, but preview snapshot missing — check server.";
    } catch (err) { msg.textContent = "Error: " + err.message; }
    finally { btn.disabled = false; }
  };
}

async function start() {
  buildFacadeSelector();
  refreshPreviews();
  buildBrushes(); buildGlazes(); buildSteps();
  selectBrush(state.brush);
  resize();
  requestAnimationFrame(draw);
  try {
    const r = await (await fetch("/api/status")).json();
    setRhino(r.rhino);
    const s = r.session;
    state.tileMm = s.tile_mm;
    state.thicknessMm = s.thickness_mm ?? 12;
    $("tileSide").value = String(s.tile_mm);
    $("thickness").value = String(state.thicknessMm);
    state.strokes = s.strokes.map(upgrade);
    tileLabel(); rebuild(); fit();
  } catch {
    setRhino(null);
  }
  setInterval(refreshPreviews, 12000);
  setInterval(() => fetch("/api/status").then((r) => r.json()).then((r) => setRhino(r.rhino)).catch(() => setRhino(null)), 6000);
}
window.addEventListener("resize", () => { resize(); sizeShow(); dilShow(); });
start();
