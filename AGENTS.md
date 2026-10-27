# AGENTS.md — Ullada

Instructions for any AI coding agent (Claude Code, Cursor, Codex) working in this repo. Read this file and `spec/constitution/` before starting any task.

## What Ullada is

A Streamlit app for Barcelona architects at the first client meeting. A client's photo or AI image plus an address becomes two priced options:

- **Cosmetic:** kitchen + bathroom
- **Efficient:** cosmetic + windows

Each option shows a cost range, energy label before/after, kWh and CO₂ saved per year, and the permit needed. Scope: flats in multi-unit buildings built 1950–1980. See `spec/constitution/mission.md`.

## Hard rules (never break)

1. **No invented numbers.** Every cost, quantity, energy value or factor comes from a file in `data/` with a `source` and `date` column, or from a deterministic calculation over those files. An LLM never writes, edits or "estimates" a number shown to the user.
2. **Always a range.** Costs are shown as low / likely / high. Never a single figure.
3. **Never call it a quote.** UI text says "estimate" or "ballpark". Every result screen shows that it must be checked by the architect.
4. **Say "not enough data".** If inputs are missing or outside scope (wrong typology, year, use), return "not enough data" with the reason. Don't fall back to a guess.
5. **The LLM only reads and asks.** Claude reads images (room type, renovation level, visible clues) and chooses questions. The engine (`src/engine.py`) does all the maths and imports no LLM code.
6. **Verified TLS only.** Never use `ssl.CERT_NONE`, `verify=False` or `check_hostname = False`. Use `certifi.where()`.
7. **No secrets in git.** API keys live in `.env` (already gitignored). Read them with `os.environ`.
8. **No client data in git.** Test photos and addresses from real clients stay out of the repo unless consent is recorded.

## Repo layout (target)

```
app.py                  Streamlit UI
src/catastro.py         address / cadastral ref → year, area, dwellings, floors
src/reader.py           image → structured reading (Claude vision, JSON out)
src/engine.py           quantities × unit prices → low / likely / high (no LLM)
src/energy.py           label + kWh before/after from data/energy_rules.csv
data/prices.csv         unit prices: code, item, unit, low, likely, high, source, date
data/energy_rules.csv   measure → label step, kWh/m²·year, source
data/questions.csv      adaptive questions and which variable each one fixes
tests/                  pytest, one file per src module
spec/constitution/      mission, tech stack, roadmap: changes only by team agreement
spec/features/<name>/   spec.md → plan.md → tasks.md for each feature
notebooks/              exploration only; nothing in the app imports from here
```

## Workflow (spec-driven)

1. Before coding a feature, write or read `spec/features/<name>/spec.md` (what and why), then `plan.md` (how), then `tasks.md` (small checkable steps).
2. Use Plan mode to agree on the plan before Build mode.
3. One task → one small commit. Run `pytest` before committing.
4. If a task needs a number that isn't in `data/`, stop and add a row with a source. Don't hardcode it.
5. Update `spec/constitution/roadmap.md` when a milestone is done.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
streamlit run app.py
```

Add a package: `pip install <pkg>`, then pin its version in `requirements.txt` in the same commit.

## Code style

- Python 3.12, type hints on public functions, docstrings that say the unit (€, m², kWh/year).
- Functions return plain dicts or dataclasses, never formatted strings. Formatting belongs in `app.py`.
- Keep modules small and testable without network access. Mock Catastro and Claude calls in tests.
- Data files are CSV with a header row, UTF-8, `.` as the decimal separator.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Building year, area, dwellings | Catastro OVC web service; INSPIRE BU bulk (08900) for exploration | Barcelona Catastro code 08900, INE 08019 |
| Unit prices | CYPE Generador de precios; BEDEC (ITeC) if access confirmed | Record the database version and date |
| Energy | CE3X runs; Catalan energy certificate open data (ICAEN) | Typology 1950–1980 flats |
| CO₂ factor | Cite the official Spanish factor used | One value, one source |
