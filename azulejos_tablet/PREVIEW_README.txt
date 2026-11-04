AZULEJOS — SINGLE TILE / CENTRE + 8 VIEW

Install: stop server with Ctrl+C, back up project and Rhino .3dm, then copy server.py and static/app.js from this folder into your existing azulejos_tablet project. Restart with py server.py; hard-refresh iPad Safari. Other files included for completeness.

The right sidebar has Single tile and Centre + 8 buttons. Selecting B3 shows A2 A3 A4 / B2 [B3] B4 / C2 C3 C4. The centre is the ONLY editable area. Neighbors are read-only snapshots of tiles previously sent to Rhino. Outside the facade, dark placeholders are shown.

The server stores previews in out/facade_previews.json after a successful Send. This file is important to keep/back up. Rhino objects placed BEFORE this feature cannot be reconstructed reliably as brush previews; re-send those cells once to populate previews. Existing placed Rhino geometry is not deleted.

Edits to the working sketch do not change a placed cell until Send is pressed. Delete tile removes its preview and Rhino geometry. Preview is a 2D approximation of brush strokes, not a live render of Rhino geometry.

No live Rhino or iPad testing was possible here.
