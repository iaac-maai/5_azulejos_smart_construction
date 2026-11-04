"""Azulejos tablet: draw on the iPad, see the strokes appear in Rhino.

    python3 server.py            # then open the printed address on the iPad
    python3 server.py --resume   # continue the latest saved drawing

The iPad and the Mac must be on the same Wi-Fi. Rhino 8 must be open with the
RhinoMCP plugin listening (type `mcpstart` in Rhino if Claude is not connected).
Each finished stroke is saved to out/<session>.json and drawn under the
layer "Azulejos tablet" in its own Rhino file, out/azulejos_tablet.3dm, which
is opened in Rhino automatically. Only the Python standard library is used.

Options (environment variables):
    AZULEJOS_PORT=8765          web server port
    AZULEJOS_ORIGIN=0,0         where the tile's bottom-left corner sits in Rhino (mm)
    AZULEJOS_RHINO_FILE=...     a different .3dm file for the tablet drawing
"""
import json
import math
import os
import socket
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import azulejos_tablet.rhino_link_backup as rhino_link_backup  # noqa: E402

STATIC = os.path.join(HERE, "static")
OUT = os.path.join(HERE, "out")
PORT = int(os.getenv("AZULEJOS_PORT", "8765"))
ORIGIN = [float(v) for v in os.getenv("AZULEJOS_ORIGIN", "0,0").split(",")]
TILE_SIZES = (100.0, 150.0, 200.0)
THICKNESSES = (8.0, 10.0, 12.0, 15.0, 20.0)   # glazed azulejo ~8-12 mm, cement tile ~15-20 mm
DEFAULT_THICKNESS = 12.0


class Session:
    """The drawing being made right now, mirrored to disk and to Rhino."""

    def __init__(self):
        self.lock = threading.Lock()
        self.new(150.0, DEFAULT_THICKNESS)

    def new(self, tile_mm, thickness_mm):
        self.name = time.strftime("%Y%m%d-%H%M%S")
        self.tile_mm = tile_mm
        self.thickness_mm = thickness_mm
        self.strokes = []          # clean stroke dicts, in drawing order
        self.next_id = 1
        self.rhino_ids = {}        # stroke id -> Rhino object ids
        self.tile_ids = []

    def to_json(self):
        return {
            "schema": "azulejos.tablet/0.2",
            "session": self.name,
            "units": "mm",
            "axes": "origin bottom-left of the tile, y up",
            "tile_mm": self.tile_mm,
            "thickness_mm": self.thickness_mm,
            "rhino_origin": ORIGIN,
            "strokes": self.strokes,
        }

    def resume(self, path):
        """Continue a saved session and redraw it in the tablet's Rhino file."""
        with open(path) as f:
            data = json.load(f)
        self.name = data["session"]
        self.tile_mm = data["tile_mm"]
        self.thickness_mm = data.get("thickness_mm", DEFAULT_THICKNESS)
        self.strokes = [upgrade(st) for st in data["strokes"]]
        self.next_id = max([st["id"] for st in self.strokes], default=0) + 1
        _, err = to_rhino(rhino_link_backup.clear_all)
        if err:  # Rhino closed or has no document open: keep the drawing, skip Rhino
            print("  Rhino not reachable ({}); the drawing is loaded but not redrawn".format(err))
            return
        self.tile_ids = rhino_link_backup.draw_tile(ORIGIN, self.tile_mm, self.thickness_mm) or []
        for st in self.strokes:
            self.rhino_ids[st["id"]] = to_rhino(rhino_link_backup.draw_stroke, ORIGIN, st, self.thickness_mm)[0] or []

    def save(self):
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, self.name + ".json")
        with open(path + ".tmp", "w") as f:
            json.dump(self.to_json(), f)
        os.replace(path + ".tmp", path)


SESSION = Session()
PLACED_PATH = os.path.join(OUT, "facade_previews.json")

def load_placed():
    try:
        with open(PLACED_PATH, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

PLACED = load_placed()

def save_placed():
    os.makedirs(OUT, exist_ok=True)
    with open(PLACED_PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(PLACED, f)
    os.replace(PLACED_PATH + ".tmp", PLACED_PATH)



def num(v, lo=-1e6, hi=1e6, default=0.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return max(lo, min(hi, v))


def clean_stroke(raw, next_id):
    """Keep only known fields as plain numbers, so nothing else reaches Rhino."""
    points = []
    for p in raw.get("points", [])[:5000]:
        points.append({
            "t": round(num(p.get("t"), 0, 1e7), 1),          # ms since stroke start
            "x": round(num(p.get("x")), 3),                  # mm
            "y": round(num(p.get("y")), 3),                  # mm, y up
            "p": round(num(p.get("p"), 0, 1, 0.5), 4),       # pressure 0-1
            "alt": round(num(p.get("alt"), 0, math.pi / 2, math.pi / 2), 4),  # rad, pi/2 = upright
            "az": round(num(p.get("az"), -2 * math.pi, 2 * math.pi), 4),      # rad
        })
    ribbon = [[round(num(x), 3), round(num(y), 3), round(num(r, 0.01, 50, 1), 3)]
              for x, y, r in raw.get("ribbon", [])[:5000]]
    brush = raw.get("brush") if raw.get("brush") in rhino_link_backup.BRUSHES else "perfilador"
    step = raw.get("step") if raw.get("step") in rhino_link_backup.STEPS else "perfilado"
    return {
        "id": next_id,
        "step": step,                                         # craft step = Rhino layer
        "brush": brush,
        "glaze": raw.get("glaze") if raw.get("glaze") in rhino_link_backup.GLAZES else "cobalt",
        "size_mm": round(num(raw.get("size_mm"), 0.1, 50, 2), 2),
        "dilution": round(num(raw.get("dilution"), 0.05, 1, 1), 3),     # pigment concentration
        "load_start": round(num(raw.get("load_start"), 0, 1, 1), 4),    # pigment on the brush
        "seed": int(num(raw.get("seed"), 0, 2 ** 31, 1)),               # brush texture, for exact redraws
        "device": raw.get("device") if raw.get("device") in ("pen", "touch", "mouse") else "unknown",
        "started": round(num(raw.get("started"), 0, 1e14)),  # epoch ms
        "points": points,
        "ribbon": ribbon,
    }


def erase_segments(strokes, path, radius, next_id):
    """Split centreline strokes wherever the eraser touches them."""
    if not path:
        return strokes, next_id
    radius2 = radius * radius
    def hit(pt):
        x, y = pt["x"], pt["y"]
        for a, b in zip(path, path[1:]):
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            t = max(0.0, min(1.0, ((x-a["x"])*dx+(y-a["y"])*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0.0
            if (x-a["x"]-t*dx)**2 + (y-a["y"]-t*dy)**2 <= radius2:
                return True
        return any((x-a["x"])**2 + (y-a["y"])**2 <= radius2 for a in path[:1])
    result = []
    for st in strokes:
        if st.get("brush") == "punzon":
            result.append(st)
            continue
        pts = st["points"]
        # Resample long segments so a thin eraser cannot pass between samples.
        dense = []
        for i, pt in enumerate(pts):
            if i:
                prev = pts[i-1]
                d = math.hypot(pt["x"]-prev["x"], pt["y"]-prev["y"])
                for j in range(1, min(250, int(d/max(0.35, radius/3)))+1):
                    t = j/(min(250, int(d/max(0.35, radius/3)))+1)
                    dense.append({key: round(prev[key]+(pt[key]-prev[key])*t, 4) for key in ("t","x","y","p","alt","az")})
            dense.append(pt)
        runs, run = [], []
        for pt in dense:
            if hit(pt):
                if len(run) >= 2: runs.append(run)
                run = []
            else:
                run.append(pt)
        if len(run) >= 2: runs.append(run)
        if len(runs) == 1 and len(runs[0]) == len(pts) and not any(hit(pt) for pt in pts):
            result.append(st)
            continue
        for run in runs:
            frag = dict(st)
            frag["id"] = next_id
            next_id += 1
            frag["points"] = run
            frag["ribbon"] = []
            result.append(frag)
    return result, next_id


def upgrade(st):
    """Strokes from the first tablet version (role + pigment) -> craft steps and glazes."""
    if "step" in st:
        return st
    role = st.get("role", "perfil")
    return {
        "id": st["id"],
        "step": "perfilado" if role == "perfil" else "relleno",
        "brush": "perfilador" if role == "perfil" else "relleno",
        "glaze": st.get("pigment", "cobalt"),
        "size_mm": st.get("tool", {}).get("size_mm", 2.0),
        "dilution": 1.0,
        "load_start": 1.0,
        "seed": st["id"] * 7919,
        "device": st.get("tool", {}).get("device", "pen"),
        "started": st.get("started", 0),
        "points": st.get("points", []),
        "ribbon": st.get("ribbon", []),
    }


def rebuild_working(session):
    """Recreate Rhino's working drawing from the authoritative server strokes.

    Prevents deleted/erased/orphaned Rhino objects being copied to a facade cell.
    """
    rhino_link_backup.clear_working()
    session.rhino_ids = {}
    session.tile_ids = rhino_link_backup.draw_tile(ORIGIN, session.tile_mm, session.thickness_mm) or []
    for stroke in session.strokes:
        session.rhino_ids[stroke["id"]] = rhino_link_backup.draw_stroke(
            ORIGIN, stroke, session.thickness_mm) or []


def to_rhino(fn, *args):
    try:
        return fn(*args), None
    except Exception as ex:  # Rhino closed, plugin not started, script error
        return None, str(ex)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in self.path:
            sys.stderr.write("  " + (fmt % args) + "\n")

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the iPad closed the page or dropped off Wi-Fi mid-request

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def reply(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/facade-previews":
            # These are stored snapshots, not editable strokes.
            return self.reply({"cells": PLACED})
        if self.path == "/api/status":
            return self.reply({"rhino": rhino_link_backup.is_up(), "session": SESSION.to_json()})
        return super().do_GET()

    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        if size > 5_000_000:
            return self.reply({"error": "too large"}, 413)
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            return self.reply({"error": "bad json"}, 400)
        s = SESSION
        with s.lock:
            if self.path == "/api/clear":
                _, err = to_rhino(rhino_link_backup.clear_working)
                if err:
                    return self.reply({"ok": False, "error": err}, 500)
                s.strokes = []
                s.rhino_ids = {}
                s.save()
                return self.reply({"ok": True, "strokes": [], "rhino": True})
            if self.path == "/api/erase":
                path = [{"x": num(pt.get("x")), "y": num(pt.get("y"))}
                        for pt in body.get("points", [])[:5000] if isinstance(pt, dict)]
                radius = num(body.get("radius_mm"), 0.5, 20, 2.5)
                before = s.strokes
                after, next_id = erase_segments(before, path, radius, s.next_id)
                # Keep existing Rhino geometry until replacement succeeds.
                _, err = to_rhino(rhino_link_backup.clear_working)
                if err:
                    return self.reply({"error": err}, 500)
                s.strokes, s.next_id, s.rhino_ids = after, next_id, {}
                _, err = to_rhino(rebuild_working, s)
                if err:
                    return self.reply({"error": err}, 500)
                s.save()
                return self.reply({"ok": True, "strokes": s.strokes, "rhino": True})
            if self.path == "/api/place":
                cell = body.get("cell", "")
                if not isinstance(cell, str) or len(cell) != 2 or cell[0] not in "ABCDE" or cell[1] not in "123456":
                    return self.reply({"ok": False, "error": "Choose A1 through E6"}, 400)
                if not s.strokes:
                    return self.reply({"ok": False, "error": "Draw a stroke first"}, 400)
                if s.tile_mm != 150:
                    return self.reply({"ok": False, "error": "Set tile size to 150 mm"}, 400)
                # Rebuild from current server strokes BEFORE copying to the cell.
                # No stale working-layer objects can survive this operation.
                _, err = to_rhino(rebuild_working, s)
                if err:
                    return self.reply({"ok": False, "error": "Could not rebuild working sketch: " + err}, 500)
                result, err = to_rhino(rhino_link_backup.place_cell, cell, ORIGIN, s.tile_mm)
                if err or not isinstance(result, dict) or result.get("cell") != cell:
                    return self.reply({"ok": False, "error": err or "Rhino did not confirm placement. Check Rhino command history."}, 500)
                PLACED[cell] = {"tile_mm": s.tile_mm, "strokes": json.loads(json.dumps(s.strokes)), "updated": time.time()}
                save_placed()
                return self.reply({"ok": True, "cell": cell, "result": result})
            if self.path == "/api/delete-cell":
                cell = body.get("cell", "")
                if not isinstance(cell, str) or len(cell) != 2 or cell[0] not in "ABCDE" or cell[1] not in "123456":
                    return self.reply({"ok": False, "error": "Choose A1 through E6"}, 400)
                result, err = to_rhino(rhino_link_backup.delete_cell, cell)
                if err or not isinstance(result, dict) or result.get("cell") != cell:
                    return self.reply({"ok": False, "error": err or "Rhino did not confirm deletion"}, 500)
                PLACED.pop(cell, None)
                save_placed()
                return self.reply({"ok": True, "cell": cell, "result": result})
            if self.path == "/api/stroke":
                stroke = clean_stroke(body, s.next_id)
                if len(stroke["points"]) < 2:
                    return self.reply({"error": "stroke too short"}, 400)
                s.next_id += 1
                s.strokes.append(stroke)
                s.save()
                if not s.tile_ids:
                    s.tile_ids, _ = to_rhino(rhino_link_backup.draw_tile, ORIGIN, s.tile_mm, s.thickness_mm)
                    s.tile_ids = s.tile_ids or []
                ids, err = to_rhino(rhino_link_backup.draw_stroke, ORIGIN, stroke, s.thickness_mm)
                s.rhino_ids[stroke["id"]] = ids or []
                return self.reply({"id": stroke["id"], "rhino": err is None, "error": err})
            if self.path == "/api/undo":
                if not s.strokes:
                    return self.reply({"strokes": 0})
                stroke = s.strokes.pop()
                s.save()
                _, err = to_rhino(rhino_link_backup.delete, s.rhino_ids.pop(stroke["id"], []))
                return self.reply({"strokes": len(s.strokes), "rhino": err is None, "error": err})
            if self.path == "/api/new":
                tile = num(body.get("tile_mm"), default=150.0)
                tile = tile if tile in TILE_SIZES else 150.0
                thick = num(body.get("thickness_mm"), default=s.thickness_mm)
                thick = thick if thick in THICKNESSES else DEFAULT_THICKNESS
                if body.get("clear_rhino"):
                    _, err = to_rhino(rhino_link_backup.clear_all)
                    if err:
                        return self.reply({"error": err}, 500)
                s.new(tile, thick)
                ids, err = to_rhino(rhino_link_backup.draw_tile, ORIGIN, tile, thick)
                s.tile_ids = ids or []
                return self.reply({"session": s.name, "tile_mm": tile, "thickness_mm": thick,
                                   "rhino": err is None, "error": err})
            if self.path == "/api/thickness":
                thick = num(body.get("thickness_mm"), default=s.thickness_mm)
                if thick not in THICKNESSES:
                    return self.reply({"error": "unknown thickness"}, 400)
                s.thickness_mm = thick
                s.save()
                # redraws the slab; the drawing moves with its top face
                ids, err = to_rhino(rhino_link_backup.draw_tile, ORIGIN, s.tile_mm, thick)
                s.tile_ids = ids or s.tile_ids
                return self.reply({"thickness_mm": thick, "rhino": err is None, "error": err})
        return self.reply({"error": "unknown endpoint"}, 404)


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            return sk.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    if "--resume" in sys.argv:
        saved = sorted(f for f in os.listdir(OUT) if f.endswith(".json")) if os.path.isdir(OUT) else []
        if saved:
            SESSION.resume(os.path.join(OUT, saved[-1]))
            print("Resumed {} ({} strokes)".format(saved[-1], len(SESSION.strokes)))
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Azulejos tablet")
    print("  on the iPad (same Wi-Fi):  http://{}:{}".format(lan_ip(), PORT))
    print("  on this Mac:               http://localhost:{}".format(PORT))
    print("  Rhino plugin:              {}".format("connected" if rhino_link_backup.is_up() else
                                                   "not found - open Rhino 8 and type mcpstart"))
    print("  Rhino file:                {}".format(rhino_link_backup.RHINO_FILE))
    print("  strokes saved to           {}".format(OUT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
