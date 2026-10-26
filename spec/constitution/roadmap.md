# Ullada — Roadmap

Ullada v1 turns a client's photo and address into two priced options, **cosmetic** (kitchen + bathroom) and **efficient** (cosmetic + windows), with cost range, energy label before/after, kWh and CO₂ saved. Users: architects in small Barcelona studios, at the first client meeting. Typology: flats in multi-unit buildings built 1950–1980.

Full checklist with details: team doc "Ullada — Build Plan, Start to Finish".

## v1 pipeline

1. Address → Catastro: year built, floor area, use (`src/catastro.py`)
2. Image → Claude vision: room, wanted level, visible clues (`src/reader.py`)
3. Adaptive questions: only what changes the answer most (`data/questions.csv`)
4. Engine: price table × quantities → low / likely / high, no LLM (`src/engine.py`)
5. Energy rules: label and kWh before/after (`data/energy_rules.csv`)
6. Streamlit app (`app.py`)

## Milestones

| Dates | Step | Done when |
|---|---|---|
| 26–29 Oct | Set up | Clean repo, shared Python env, AGENTS.md, spec files, interviews booked |
| 29 Oct–5 Nov | Data first + midterm | `catastro.py` passes tests on 3 addresses; `prices.csv` has 30 sourced rows; certificate data filtered; 20 test images with AI readings logged; midterm submitted 5 Nov |
| 6–12 Nov | First feature | `engine.py` + tests pass; €/m² baseline; Claude Code answers through our MCP server |
| 13–19 Nov | Hackathon beta | Photo + address → two options in Streamlit, run by a teammate unaided |
| 20–26 Nov | Energy + harness | `energy_rules.csv` from CE3X runs; CO₂ factor cited; permits and subsidies researched; AGENTS.md rules tested |
| 27 Nov–3 Dec | Proof | Results table vs €/m² rule and architects on ≥15 cases; range honesty ≈80% target |
| 4–17 Dec | Ethics + final | Consent and privacy in the app; interface tested with an architect; live demo, deck, Lean Canvas, blog post |

## Later (only if time allows)

- "Deep" option: heat pump and interior insulation
- AI chooses the next question by remaining uncertainty
- Window sizes from the photo (Metric3D), checked against known dimensions
