---
status: accepted
---

# The Mosaic is a tile-aligned COG that clients read directly

Each Slot's Mosaic is one Cloud Optimized GeoTIFF in Web Mercator whose 512 px
internal tiles, at full resolution (zoom 8, 611 m per pixel at the equator) and
at every overview, are the standard web map tiles. A client reads the header
once, then fetches a tile with one byte-range request and decodes it natively,
so nothing has to run between the bucket and the map. We chose this so the
product is one reusable file per Slot and needs no service of its own.

## Considered Options

- **A tree of XYZ tile files.** Readable by every map client without new code,
  but tens of thousands of files per Slot and nothing another service can open
  as one image.
- **A tile endpoint that cuts tiles out of the COG.** Keeps clients trivial, but
  it is a service to run and deploy; rejected for that reason.
- **A COG in EPSG:4326.** Suits a globe renderer with a geographic surface, but
  its tiles are not web map tiles, so every browser tile would need decoding and
  redrawing.
- **A general GeoTIFF reader in the browser** (`geotiff.js`). Works with any
  layout, at the price of decoding every tile in JavaScript.

## Consequences

- The layout is a contract. A Mosaic whose overviews are not aligned, or whose
  tiles are not complete images, breaks its readers. The encode step checks the
  alignment of every overview level on each Mosaic and fails if one is off.
- Transparency lives inside the tiles, never in a separate mask.
- The bucket must answer cross-origin range requests.
- A header is good only for the file it was read from. A rebuilt Mosaic
  replaces its file under the same name, so a client sends `If-Match` with the
  header's ETag on each tile request and reads the header again on a 412.
- Zoom 8 is 1.2 times coarser than the finest band directly under each
  satellite. That detail is given up: the Renderings, which keep it, are
  working files and are not published.
