"""Talk to Rhino through the RhinoMCP plugin that is already running inside Rhino.

The plugin (started in Rhino with `mcpstart`) listens on 127.0.0.1:1999. Every
message is a 4-byte big-endian length followed by UTF-8 JSON
{"type": <command>, "params": {...}}. This is the same socket the rhinomcp MCP
server uses, so Claude and the tablet can work in the same Rhino session.

All tablet geometry goes into its own file (out/azulejos_tablet.3dm by
default), never into whatever document happens to be active. The file is
created and opened in Rhino on first use.

Only this module writes Rhino code. The tablet sends numbers, never code.
"""
import json
import math
import os
import socket
import textwrap
import threading

HOST = "127.0.0.1"
PORT = int(os.getenv("RHINO_MCP_PORT", "1999"))
TIMEOUT = 15.0

ROOT_LAYER = "Azulejos tablet"
REPO = os.path.dirname(os.path.abspath(__file__))
RHINO_FILE = os.path.abspath(os.getenv(
    "AZULEJOS_RHINO_FILE", os.path.join(REPO, "out", "azulejos_tablet.3dm")))
# in-glaze pigments, approximate fired colour (same ids as static/engine.js)
GLAZES = {
    "cobalt": (31, 63, 154),
    "manganese": (91, 44, 71),
    "antimony": (227, 162, 31),
    "copper": (59, 139, 70),
    "iron": (207, 109, 29),
    "black": (29, 25, 28),
    "charcoal": (58, 54, 51),     # estarcido: pounced charcoal (burns away in the kiln)
    "white": (246, 242, 232),     # esgrafiado: scratched back to the tin-white glaze
}
# craft steps, each a Rhino sub-layer
STEPS = ("estarcido", "perfilado", "relleno", "esgrafiado")
BRUSHES = ("munequilla", "perfilador", "relleno", "paletina", "esponja", "punzon")
INK_LIFT = 0.02   # mm above the glaze, so the ink does not flicker into the slab

_lock = threading.Lock()



def send(command, params=None):
    """Send a command to Rhino MCP and read its JSON response."""
    body = json.dumps({
        "type": command,
        "params": params or {}
    }).encode("utf-8")

    with _lock, socket.create_connection((HOST, PORT), timeout=TIMEOUT) as sock:
        sock.settimeout(TIMEOUT)

        # Rhino MCP expects raw JSON, not a length-prefixed message.
        sock.sendall(body)

        # Read until a complete JSON response is received.
        decoder = json.JSONDecoder()
        chunks = []

        while True:
            chunk = sock.recv(8192)

            if not chunk:
                raise ConnectionError("Rhino closed the connection")

            chunks.append(chunk)

            try:
                response, _ = decoder.raw_decode(
                    b"".join(chunks).decode("utf-8").strip()
                )
                return response
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue



def _read(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Rhino closed the connection")
        data += chunk
    return data


def run_python(code):
    """Execute Rhino code and decode the AZULEJOS marker across MCP output variants."""
    result = send("execute_rhinoscript_python_code", {"code": code})
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected Rhino response: {!r}".format(result)[:500])
    if result.get("success") is False or result.get("status") == "error":
        raise RuntimeError(str(result.get("message") or result.get("error") or result.get("output") or result)[:1200])

    def strings(value):
        if isinstance(value, str):
            yield value
            # Some plugin versions JSON-encode the Python output a second time.
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                return
            if decoded != value:
                yield from strings(decoded)
        elif isinstance(value, dict):
            for key in ("output", "result", "content", "text", "message", "data", "stdout"):
                if key in value:
                    yield from strings(value[key])
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    import re
    for output in strings(result):
        for line in reversed(output.splitlines()):
            match = re.search(r"AZULEJOS:\s*(.+)$", line)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except ValueError:
                    pass
    # Never report a successful Rhino placement when the plugin has not
    # actually returned the confirmation marker.
    raise RuntimeError("Rhino returned no AZULEJOS confirmation. Response: {}".format(repr(result)[:900]))


def is_up():
    try:
        send("get_document_summary")
        return True
    except Exception:
        return False


_HEADER = '''
import json
import os
import Rhino
import scriptcontext as sc
import rhinoscriptsyntax as rs
import System
DATA = json.loads(r"""{data}""")
ROOT = "{root}"
TARGET = os.path.normpath(r"""{file}""")

def target_doc():
    for d in Rhino.RhinoDoc.OpenDocuments():
        if d.Path and os.path.normpath(d.Path) == TARGET:
            return d
    if not os.path.exists(TARGET):
        new = Rhino.RhinoDoc.CreateHeadless(None)
        new.ModelUnitSystem = Rhino.UnitSystem.Millimeters
        new.Write3dmFile(TARGET, Rhino.FileIO.FileWriteOptions())
        new.Dispose()
    opened = Rhino.RhinoDoc.Open(TARGET)
    return opened[0] if isinstance(opened, tuple) else opened

_previous = sc.doc
sc.doc = target_doc()

INK_LIFT = {lift}

def layer(name, color):
    full = ROOT + "::" + name
    if not rs.IsLayer(ROOT):
        rs.AddLayer(ROOT)
    if not rs.IsLayer(full):
        rs.AddLayer(name, color, parent=ROOT)
    return full
'''

_FOOTER = '''
finally:
    sc.doc.Views.Redraw()
    sc.doc.Save()
    sc.doc = _previous
'''

_TILE = '''
ox, oy, s, t = DATA["origin"][0], DATA["origin"][1], DATA["tile_mm"], DATA["thickness_mm"]
lay = layer("tile", (120, 120, 130))
old = rs.ObjectsByLayer(lay) or []
old_top = max(p[2] for p in rs.BoundingBox(old)) if old else 0.0
if old:
    rs.DeleteObjects(old)
# the fired tile: a solid slab, glaze on top at z = thickness
bottom = [(ox, oy, 0), (ox + s, oy, 0), (ox + s, oy + s, 0), (ox, oy + s, 0)]
box = rs.AddBox(bottom + [(x, y, t) for x, y, _ in bottom])
rs.ObjectLayer(box, lay)
rs.ObjectColor(box, (244, 239, 227))
rs.ObjectName(box, "tile {:.0f} x {:.0f} x {:g} mm".format(s, s, t))
rs.SetUserText(box, "azulejos_tile", json.dumps({"side_mm": s, "thickness_mm": t}))
# keep the drawing on the glaze when the thickness changes
dz = t - old_top if old else 0.0
drawn = []
for name in rs.LayerNames():
    if name.startswith(ROOT + "::") and name != lay:
        drawn += rs.ObjectsByLayer(name) or []
if drawn and abs(dz) > 1e-9:
    rs.MoveObjects(drawn, (0, 0, dz))
# show the tile in every viewport, with a margin; shaded perspective shows the slab
m = s * 0.15
rs.ZoomBoundingBox([(ox - m, oy - m, 0), (ox + s + m, oy + s + m, t)], all=True)
if "Perspective" in (rs.ViewNames() or []):
    rs.ViewDisplayMode("Perspective", "Shaded")
print("AZULEJOS:" + json.dumps([str(box)]))
'''

_STROKE = '''
ox, oy = DATA["origin"]
st = DATA["stroke"]
ids = []
ink = layer(st["step"], tuple(DATA["color"]))
z = DATA["z"]
# Clamp centreline to the physical tile before creating Rhino geometry.
tile_side = DATA.get("tile_mm", 150.0)
def clamp_xy(x, y, margin=0.0):
    margin = min(max(margin, 0.0), tile_side / 2.0)
    return (ox + max(margin, min(tile_side - margin, x)),
            oy + max(margin, min(tile_side - margin, y)))
pts = []

for p in st["points"]:
    x, y = clamp_xy(p["x"], p["y"])
    pts.append((x, y, z))
clean = [pts[0]]
for p in pts[1:]:
    if rs.Distance(p, clean[-1]) > 0.05:
        clean.append(p)
if len(clean) >= 2:
    step = max(1, len(clean) // 120)
    simple = clean[::step]
    if simple[-1] != clean[-1]:
        simple.append(clean[-1])
    crv = rs.AddPolyline(simple)  # interpolating splines overshoot tile boundaries
    if crv:
        rs.ObjectLayer(crv, ink)
        rs.ObjectColor(crv, tuple(DATA["color"]))   # pigment, not the layer's colour
        rs.ObjectName(crv, "stroke {}".format(st["id"]))
        rs.SetUserText(crv, "azulejos_stroke", json.dumps({k: v for k, v in st.items() if k not in ("outline", "ribbon")}))
        ids.append(str(crv))
# the filled brush mark: a ribbon mesh along the smoothed centre line, width from
# pressure, round ends. Its outline (overlaps merged, holes kept) is hatched, so
# strokes that cross themselves fill too. The outline is also the cut line for
# a stencil later.
import math
from Rhino.Geometry import Mesh, Plane, Point3d, Vector3d
rib = []
for x, y, r in st["ribbon"]:
    cx, cy = clamp_xy(x, y, r)
    c = Point3d(cx, cy, z)
    if not rib or c.DistanceTo(rib[-1][0]) > 0.05:
        rib.append((c, r))
mesh = Mesh()
n = len(rib)
tangents = []
for i in range(n):
    t = rib[min(i + 1, n - 1)][0] - rib[max(i - 1, 0)][0]
    if not t.Unitize():
        t = Vector3d.XAxis
    tangents.append(t)
    side = Vector3d(-t.Y, t.X, 0)
    for sign in (1, -1):
        v = rib[i][0] + side * (sign * rib[i][1])
        vx, vy = clamp_xy(v.X - ox, v.Y - oy)
        mesh.Vertices.Add(vx, vy, z)
for i in range(n - 1):
    a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2
    mesh.Faces.AddFace(a, b, c)
    mesh.Faces.AddFace(a, c, d)
for i, back in ((0, -1.0), (n - 1, 1.0)) if n else ():
    centre, r = rib[i]
    t = tangents[i] * back
    side = Vector3d(-tangents[i].Y, tangents[i].X, 0)
    cap_x, cap_y = clamp_xy(centre.X - ox, centre.Y - oy)
    k = mesh.Vertices.Add(cap_x, cap_y, z)
    arc = []
    for j in range(13):
        a = math.pi * j / 12.0
        v = centre + (side * math.cos(a) + t * math.sin(a)) * r
        vx, vy = clamp_xy(v.X - ox, v.Y - oy)
        arc.append(mesh.Vertices.Add(vx, vy, z))
    for j in range(12):
        mesh.Faces.AddFace(k, arc[j], arc[j + 1])
mesh.Normals.ComputeNormals()
mesh.Compact()
fill = layer("ink", (60, 60, 60))
edge = layer("ink outline", (60, 60, 60))
color = tuple(DATA["color"])
outlines = [pl for pl in (mesh.GetOutlines(Plane(Point3d(0, 0, z), Vector3d.ZAxis)) or []) if pl.IsValid and pl.Count > 3]
curves = []
for pl in outlines:
    cid = sc.doc.Objects.AddPolyline(pl)
    if cid != System.Guid.Empty:
        rs.ObjectLayer(cid, edge)
        rs.ObjectColor(cid, color)
        curves.append(cid)
        ids.append(str(cid))
if sc.doc.HatchPatterns.FindName("Solid") is None:
    sc.doc.HatchPatterns.Add(Rhino.DocObjects.HatchPattern.Defaults.Solid)
hatches = []
if curves:
    try:
        hatches = rs.AddHatches(curves, "Solid") or []
    except Exception:
        hatches = []
for h in hatches:
    rs.ObjectLayer(h, fill)
    rs.ObjectColor(h, color)
    ids.append(str(h))
if not hatches and mesh.Faces.Count:
    # outline failed (very tangled stroke): keep the ribbon mesh itself
    mid = sc.doc.Objects.AddMesh(mesh)
    rs.ObjectLayer(mid, fill)
    rs.ObjectColor(mid, color)
    ids.append(str(mid))
print("AZULEJOS:" + json.dumps(ids))
'''

_DELETE = '''
ids = [i for i in DATA["ids"] if rs.IsObject(i)]
if ids:
    rs.DeleteObjects(ids)
print("AZULEJOS:" + json.dumps(len(ids)))
'''

_CLEAR_WORKING = r'''
# Remove all working sketch objects, including those from previous server runs.
# Keep the tile slab and every placed facade cell untouched.
ids = []
for name in rs.LayerNames():
    if name.startswith(ROOT + "::") and name != ROOT + "::tile":
        ids.extend(rs.ObjectsByLayer(name) or [])
if ids:
    rs.DeleteObjects(ids)
print("AZULEJOS:" + json.dumps(len(ids)))
'''

_CLEAR = '''
ids = []
for name in rs.LayerNames():
    if name.startswith(ROOT + "::"):
        ids += rs.ObjectsByLayer(name) or []
if ids:
    rs.DeleteObjects(ids)
print("AZULEJOS:" + json.dumps(len(ids)))
'''


def _code(body, data):
    """Wrap a script body so it runs in the tablet file and always switches back."""
    head = _HEADER.replace("{root}", ROOT_LAYER).replace("{file}", RHINO_FILE)
    head = head.replace("{lift}", repr(INK_LIFT))
    head = head.replace("{data}", json.dumps(data))
    return head + "try:\n" + textwrap.indent(body.strip("\n"), "    ") + "\n" + _FOOTER


def draw_tile(origin, tile_mm, thickness_mm):
    """(Re)draw the tile slab; strokes already drawn move up or down with its top face."""
    return run_python(_code(_TILE, {"origin": origin, "tile_mm": tile_mm, "thickness_mm": thickness_mm}))


THINNING = {"perfilado": 0.65, "relleno": 0.3}


def ribbon_from_points(stroke):
    """Brush centre line [x, y, r] for strokes saved before the iPad sent one."""
    size = stroke.get("size_mm", 2.0)
    thin = THINNING.get(stroke["step"], 0.5)
    pen = stroke.get("device") == "pen"
    out, pressure = [], None
    for pt in stroke["points"]:
        p = pt.get("p", 0.5) if pen else 0.5
        pressure = p if pressure is None else pressure + (p - pressure) * 0.35
        if out and math.hypot(pt["x"] - out[-1][0], pt["y"] - out[-1][1]) < 0.3:
            continue
        out.append([pt["x"], pt["y"], max(0.05, size * (0.5 - thin * (0.5 - pressure)))])
    # light smoothing of the raw pencil path, like the iPad's streamline
    for _ in range(2):
        out = [out[0]] + [[(a[0] + 2 * b[0] + c[0]) / 4, (a[1] + 2 * b[1] + c[1]) / 4, b[2]]
                          for a, b, c in zip(out, out[1:], out[2:])] + [out[-1]] if len(out) > 2 else out
    return out


def draw_stroke(origin, stroke, thickness_mm):
    color = GLAZES.get(stroke["glaze"], GLAZES["cobalt"])
    if not stroke.get("ribbon"):
        stroke = dict(stroke, ribbon=ribbon_from_points(stroke))
    # scratches sit just above the paint so they read as white lines over it
    lift = INK_LIFT * (2 if stroke["step"] == "esgrafiado" else 1)
    data = {"origin": origin, "stroke": stroke, "color": color, "z": thickness_mm + lift, "tile_mm": 150.0}
    return run_python(_code(_STROKE, data))


def delete(ids):
    if not ids:
        return 0
    return run_python(_code(_DELETE, {"ids": list(ids)}))


def clear_working():
    """Clear current working drawing, including orphan geometry from older sessions."""
    return run_python(_code(_CLEAR_WORKING, {}))


def clear_all():
    """Remove every tablet object from the tablet file (before replaying a session)."""
    return run_python(_code(_CLEAR, {}))


# The facade is separate from the working tablet layers, so "New tile" and
# "Clear" never delete placed cells. A1 is top-left, E6 bottom-right.
_FACADE_PLACE = r''' 
import re
cell = DATA["cell"]
side = DATA["tile_mm"]
ox, oy = DATA["origin"]
row = ord(cell[0]) - ord("A")
col = int(cell[1:]) - 1
facade = "Azulejos facade"
if not rs.IsLayer(facade):
    rs.AddLayer(facade)
cell_layer = facade + "::" + cell
if not rs.IsLayer(cell_layer):
    rs.AddLayer(cell, (120, 145, 180), parent=facade)
source = []
for name in rs.LayerNames():
    if name.startswith(ROOT + "::"):
        for obj in rs.ObjectsByLayer(name) or []:
            if name == ROOT + "::tile" or rs.GetUserText(obj, "azulejos_stroke") is not None or name in (ROOT + "::ink", ROOT + "::ink outline"):
                source.append(obj)
if not source:
    raise RuntimeError("No live tablet geometry to place. Draw a stroke first.")
# Copy the XY working tile into a vertical XZ facade. Positive Y faces the viewer.
new_ids = rs.CopyObjects(source)
if not new_ids:
    raise RuntimeError("Rhino could not copy the tablet geometry")
rs.MoveObjects(new_ids, (-ox, -oy, 0))
rs.RotateObjects(new_ids, (0, 0, 0), 90, axis=(1, 0, 0))
rs.MoveObjects(new_ids, (col * side, 0, (4 - row) * side))
for obj in new_ids:
    rs.ObjectLayer(obj, cell_layer)
    rs.SetUserText(obj, "azulejos_cell", cell)
# Only remove the previous cell after the replacement has been created.
old = [obj for obj in (rs.ObjectsByLayer(cell_layer) or []) if obj not in new_ids]
replaced = len(old)
if old:
    rs.DeleteObjects(old)
# Draw the grid once, using a distinct layer that cannot be cleared by the tablet.
grid = facade + "::grid"
if not rs.IsLayer(grid):
    rs.AddLayer("grid", (100, 100, 100), parent=facade)
if not (rs.ObjectsByLayer(grid) or []):
    for c in range(7):
        line = rs.AddLine((c * side, 0, 0), (c * side, 0, 5 * side))
        rs.ObjectLayer(line, grid)
    for rr in range(6):
        line = rs.AddLine((0, 0, rr * side), (6 * side, 0, rr * side))
        rs.ObjectLayer(line, grid)
    for rr, letter in enumerate("ABCDE"):
        for cc in range(6):
            dot = rs.AddTextDot(letter + str(cc + 1), (cc * side + side / 2, -0.5, (4 - rr) * side + side / 2))
            rs.ObjectLayer(dot, grid)
print("AZULEJOS:" + json.dumps({"cell": cell, "objects": len(new_ids), "replaced": replaced}))
'''

def place_cell(cell, origin, tile_mm):
    """Publish a copy of the current working tile into the named facade cell."""
    if not isinstance(cell, str) or len(cell) != 2 or cell[0] not in "ABCDE" or cell[1] not in "123456":
        raise ValueError("Cell must be A1 through E6")
    if tile_mm != 150:
        raise ValueError("Facade grid requires a 150 mm working tile")
    return run_python(_code(_FACADE_PLACE, {"cell": cell, "origin": origin, "tile_mm": tile_mm}))


_FACADE_DELETE = r'''
cell = DATA["cell"]
cell_layer = "Azulejos facade::" + cell
ids = rs.ObjectsByLayer(cell_layer) or [] if rs.IsLayer(cell_layer) else []
if ids:
    rs.DeleteObjects(ids)
print("AZULEJOS:" + json.dumps({"cell": cell, "deleted": len(ids)}))
'''

def delete_cell(cell):
    """Delete only the selected published facade cell, never the grid or working sketch."""
    if not isinstance(cell, str) or len(cell) != 2 or cell[0] not in "ABCDE" or cell[1] not in "123456":
        raise ValueError("Cell must be A1 through E6")
    return run_python(_code(_FACADE_DELETE, {"cell": cell}))
