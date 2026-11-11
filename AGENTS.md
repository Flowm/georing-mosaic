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
  items". Then, by the area being touched:
  - downloads: "Data sources"
  - rendering or joining satellites: "satpy"
  - flows, the compose file or deployments: "Prefect"
  - writing the products, or reading them in satvis: "COG, writing and reading"
- **`docs/adr/`** — the decisions that were trade-offs, with the alternatives
  they beat. Read the one on an area before changing how it works.

## Conventions

- The plan is the single record of decisions. Change it in the same commit as
  the code that departs from it, and move a settled "Open items" entry into
  "Decisions".
- A figure under the plan's "Estimates" is unmeasured. Replace it with the
  measurement as soon as a run produces one.
