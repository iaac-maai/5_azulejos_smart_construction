# Ullada — Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Team knows it; geospatial wheels are stable on 3.12 |
| Environment | `.venv` + pinned `requirements.txt` | Same versions on all three laptops |
| UI | Streamlit | Fast to build, easy to demo, no front-end work |
| Image reading | Claude vision (Anthropic API), JSON output | Reads room, level and clues; never produces numbers |
| Building data | Catastro OVC web service (live), INSPIRE BU GML (exploration) | Official, free, covers every Barcelona building |
| Geometry | geopandas, pyogrio, shapely | Read GML, match coordinates to buildings |
| Prices | CSV from CYPE (chapter Z energy rehab, kitchen/bath chapters), BEDEC if access confirmed | Catalan reference prices with sources |
| Energy | Rules table from CE3X runs, checked against Catalan certificate open data | Simple, explainable, no simulation at runtime |
| Uncertainty | Monte Carlo over low/likely/high (triangular), numpy | Produces honest ranges |
| Tests | pytest, network calls mocked | Engine must be testable offline |
| Agent tooling | Claude Code with AGENTS.md, Plan/Build modes, MCP for data access | Studio method: spec-driven development |

## Endpoints

- Coordinates → cadastral ref, and ref → coordinates:
  `https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCoordenadas.asmx/Consulta_CPMRC?Provincia=BARCELONA&Municipio=BARCELONA&SRS=EPSG:25831&RC=<ref>`
- Barcelona bulk buildings:
  `https://www.catastro.hacienda.gob.es/INSPIRE/Buildings/08/08900-BARCELONA/A.ES.SDGC.BU.08900.zip`

## Constraints

- TLS is always verified (`certifi`). No `CERT_NONE`.
- API keys in `.env`, never in code or notebooks.
- The app works with Claude switched off: the image step falls back to manual answers.
