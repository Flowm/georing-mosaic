---
status: accepted
---

# Products are compressed as lossy WebP

Mosaics and Renderings are written as lossy WebP at quality 90. Each WebP tile
in a COG is a complete image that every browser and iOS 14 or later decodes
natively, which is what lets clients read tiles by byte range with no extra
step (ADR 0001). Compression stays a setting per product.

## Considered Options

- **JPEG.** Universal, but a JPEG tile in a COG is not a complete image: every
  client would have to prepend the file's shared table block.
- **JPEG XL.** Compresses better and its tiles are complete images, but it
  reached Chrome 155 and Firefox 158 only in autumn 2026, the pip-installed
  `rasterio` cannot write it, and `geotiff.js` cannot read it. Revisit once
  those change.
- **AVIF.** Not available as a COG codec in GDAL.
- **Lossless (WebP, ZSTD).** Four to seven times the size by estimate. Kept as a
  setting for Renderings when an exact comparison against GeoColor is wanted.

## Consequences

- Lossy WebP always halves colour resolution, as GDAL's JPEG does, so it cannot
  be made visually lossless.
- Encoding is slow: by a derived estimate about 19 core-minutes per Mosaic.
