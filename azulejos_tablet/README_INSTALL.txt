AZULEJOS SEND FIX — 2026-11-03

1. Stop the running server in VS Code using Ctrl+C.
2. Make a backup of your existing azulejos_tablet project folder.
3. Copy rhino_link.py and server.py from this ZIP into the existing azulejos_tablet folder, replacing those two files only.
4. Do NOT replace or delete the out folder, your .3dm file, or facade_previews.json.
5. Keep Rhino 8 open with mcpstart running. Restart the server: py server.py
6. Reload the browser page and try Send sketch to D1 again.

What changed:
- Parse Rhino MCP script output across nested, list, JSON-encoded and prefixed response formats.
- If Rhino gives no confirmation, show the actual response excerpt instead of a generic message.
- Clamp the ribbon cap center inside tile bounds.

This patch was syntax-checked but cannot be end-to-end tested against your Rhino MCP session here.
If Send still fails, copy the exact new error message from the app or VS Code terminal.
