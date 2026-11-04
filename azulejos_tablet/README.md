# Azulejos tablet: draw on the iPad, build in Rhino

The artisan draws on an iPad with the Apple Pencil, in the browser, with nothing to install on the iPad. Each finished stroke is stored in tile millimetres with its timing, pressure and pencil angle. A small server on the Mac draws it straight into Rhino through the RhinoMCP plugin, the same link Claude uses. The drawing always goes into its own file, `out/azulejos_tablet.3dm`, which opens in Rhino automatically and is saved after every stroke. Other open Rhino projects are never touched.

```
iPad Safari (Pencil)  --Wi-Fi, HTTP-->  server.py (Mac)         --TCP 1999-->  RhinoMCP plugin in Rhino 8
  static/app.js                          saves out/*.json                 layer "Azulejos tablet"
```

This project grew out of the camera-gesture prototype in [5_azulejos_smart_construction](https://github.com/iaac-maai/5_azulejos_smart_construction) (MediaPipe hand tracking → Rhino), and is kept as a separate repository.

## Run it

1. Open Rhino 8. If Claude is already connected to Rhino, the plugin is running. If not, type `mcpstart` in Rhino.
2. On the Mac, run:
   ```bash
   python3 server.py
   ```
   It prints an address such as `http://172.16.21.5:8765`. It uses only the Python standard library, so no venv is needed.
3. On the iPad, on the same Wi-Fi, open that address in Safari. Share → *Add to Home Screen* gives a full-screen app.
4. Draw. Each stroke appears in `azulejos_tablet.3dm` when you lift the Pencil.

`python3 server.py --resume` continues the latest saved drawing. It redraws it in Rhino, and undo keeps working.

Options:
- `AZULEJOS_ORIGIN=0,-400` sets where the tile's bottom-left corner sits in Rhino, in mm.
- `AZULEJOS_PORT=8765` sets the server port.
- `AZULEJOS_RHINO_FILE=/path/file.3dm` sends the drawing to another file.

## Painting like a tile painter

The interface is built for *pintura sobre cubierta*, the majolica technique of Seville, Triana and Portuguese azulejos: pigments painted onto raw tin-white glaze, then fired.

**Brushes** (right panel). Each one belongs to a craft step:

| brush | step | behaviour |
|---|---|---|
| Muñequilla (pounce bag) | estarcido | charcoal dots, as when pouncing through a *trepa*; burns away in the kiln |
| Perfilador (long liner) | perfilado | thin outline; pressure makes the line swell |
| Pincel de relleno (round fill) | relleno | soft, holds plenty of pigment; tilt the pencil for broader marks; pools where you lift |
| Paletina (flat wash) | relleno | wide flat brush for diluted washes; the flat edge follows the pencil's direction |
| Esponja (sponge) | relleno | dabbed texture for skies and backgrounds |
| Punzón (needle) | esgrafiado | scratches pigment away to bring back the white glaze |

**In-glaze pigments.** Azul cobalto, morado de manganeso, amarillo de antimonio, verde de cobre, naranja de hierro and negro. Each has a raw and a fired colour. The colours are approximations, to be checked against workshop test tiles.

**Kiln preview.** *Crudo* shows what the painter really sees: dull raw pigments on powdery glaze, plus the charcoal guide. *Cocido* shows the fired result: saturated colours, gloss, and the charcoal burnt away.

**Material behaviour:**
- The brush carries a pigment load that runs out along the stroke and breaks up into dry-brush marks. Tap the pot on the left rail, or a glaze, to dip again. Each brush keeps its own load.
- Strokes soak into the glaze: they multiply, so overlaps get darker and nothing smudges.
- The left rail has the two Procreate-style sliders: **size** (logarithmic, in mm) and **pigment** (concentration, for washes).

**Craft steps instead of layers.** Estarcido, perfilado, relleno and esgrafiado, each with a visibility toggle and a stroke count. Each step is its own sub-layer in Rhino.

**Fingers:**
- two-finger tap: undo
- three-finger tap: redo
- pinch: zoom and rotate the tile
- drag: move it

After the first Pencil touch, fingers never paint. On a Mac, the mouse paints and the scroll wheel zooms.

## What it records

Each stroke in `out/<session>.json` (schema `azulejos.tablet/0.2`):

| field | meaning |
|---|---|
| `points[].t` | ms since the stroke started (from coalesced pencil events, up to 240 Hz) |
| `points[].x`, `y` | mm, origin at the tile's bottom-left, y up |
| `points[].p` | pressure, 0–1 |
| `points[].alt`, `az` | Pencil altitude and azimuth in radians (π/2 = upright) |
| `step`, `brush`, `glaze` | craft step, artisan brush, pigment |
| `size_mm`, `dilution`, `load_start` | brush size, pigment concentration, pigment on the brush when the stroke began |
| `seed` | brush texture seed, so the stroke redraws identically |
| `ribbon` | `[x, y, radius]` along the brush path, used to build the mark in Rhino |

The tile is a solid slab on `Azulejos tablet::tile`. Choose the side (100, 150 or 200 mm, applied with **New tile**) and the thickness (8, 10, 12, 15 or 20 mm) from the tile button at the top left. A thickness change applies immediately, and the painting moves with the glaze surface.

In Rhino, each stroke lies on the tile's top face and becomes:
- a centre-line curve on `Azulejos tablet::<step>`, coloured with the fired pigment and carrying the stroke data as user text `azulejos_stroke`
- the filled brush mark on `Azulejos tablet::ink`, with its clean outline on `::ink outline`, ready to become a stencil cut line later

Scratches (esgrafiado) are drawn as white marks just above the paint. Sponge texture and dry-brush breaks are not modelled in Rhino yet; there the mark is a solid band.

## Roadmap

1. **Pencil → Rhino** (done). One tile in mm, with stroke data kept.
2. **Tile → façade.** Repeat the tile over a façade surface in Rhino with joints and the usual azulejo symmetries: draw a quarter, then mirror or rotate.
3. **Panel mode.** The iPad becomes a window onto one tile of a large composition. A stroke that crosses a tile edge continues on the next tile, and every tile is numbered for the wall.
4. **Scale translation.** Enlarging a design should not scale the brush. Keep stroke width and character from the recorded pressure and speed while the composition grows.
5. **Back to the workshop.** Generate per-tile stencils (*trepa*, pounce holes along the perfil lines) as laser-cut files, plus a tile map and pigment quantities.
6. **Firing.** Preview shrinkage (about 8%) and fired colour before the tiles are made.

Claude comes in at steps 2–4, for example: "lay this tile on the south façade with a 4-tile repeat". It works through the same RhinoMCP link, which answers the course question *why AI and not a rule*.
