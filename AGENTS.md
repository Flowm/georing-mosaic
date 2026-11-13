# AGENTS.md

Hourly colour imagery of the whole Earth from raw geostationary satellite scans:
a Python pipeline (satpy renders, Prefect orchestrates) that writes Cloud
Optimized GeoTIFFs and a static STAC catalogue.

## Where things are written down

- **`GLOSSARY.md`** — the vocabulary: Slot, Disk, Recipe, Rendering, Mosaic,
  Seam. Use its names in code and discussion, and sharpen an entry when a term
  drifts. "Composite" here means satpy's band recipes only.
- **`docs/plan.md`** — what is decided, what to build next and what is open.
  Before starting work, read "Build order" for the current milestone and "Open
  items".
- **`docs/notes.md`** — what was looked up and measured: the evidence behind
  the plan. Read the section for the area being touched:
  - downloads: "Data sources"
  - rendering or joining satellites: "satpy"
  - the flow, the compose file or the deployment: "Prefect"
  - writing the Mosaic, or reading it in satvis: "COG, writing and reading"
  - what a Slot costs: "Measurements"
- **`docs/adr/`** — the decisions that were trade-offs, with the alternatives
  they beat. Read the one on an area before changing how it works.

## Working here

- The commands are the scripts in `pyproject.toml`; each explains itself with
  `--help`. The flow runs in the compose stack, as `compose.yaml` describes.
- `out/` and `work/` are local and untracked. Keep `work/comparison/`: it holds
  the Comparison scenes' Disks and their references, and the source of the
  references keeps only some weeks.
- A render takes four minutes on eight cores and peaks at 22 GB. Run one build
  at a time, and leave `src/` alone while one runs: every step starts a fresh
  process and imports the code as it is then.
- Judge a change to the Recipe (`src/georing/satpy`, `src/georing/recipe.py`)
  with `georing-compare`, by its figures and by looking at the image pairs.
- The tests fake the heavy steps. A change to a step is proven by building a
  Slot.

## Conventions

- The plan is the single record of decisions. Change it in the same commit as
  the code that departs from it, and move a settled "Open items" entry into
  "Decisions".
- The notes are the record of what was measured. When a run produces a figure
  that replaces one there, change it in the same commit.
