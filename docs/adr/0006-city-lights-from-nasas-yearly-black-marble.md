---
status: accepted
---

# City lights from NASA's yearly Black Marble, built once by the flow

The night layer's city lights came from NASA's Black Marble 2016 picture at
3 km, warped onto each satellite's infrared grid (2 km) before the night
layer was finished, and then brought up to the finest grid by repeating
pixels. Towns came out as blobs, roads not at all, and the lights were nine
years old; CIRA's GeoColor shows towns and roads. So:

- **The source is VJ146A4, NASA's yearly Black Marble from NOAA-20,
  collection 2, year 2025**: VIIRS Day/Night Band radiance corrected for
  moonlight and the atmosphere, at 15 arc seconds (about 500 m). Two of its
  layers are kept: the radiance of the snow-free part of the year from all
  view angles, and the land/water mask, which tells unlit land (dark purple
  in the Recipe) from sea (a dark grey). Radiance, not a finished picture, so the
  Recipe colours it by its own curve.
- **The flow builds it, once.** A task `city-lights`, beside the downloads of
  every Slot, checks for the COG under the work directory and, if it is not
  there, downloads the 540 tiles of HDF5 (51 GB) from LAADS, keeps the two
  layers of each as it arrives and writes one global COG of two uint16
  bands, 355 MB. Renders wait for it. A build that is stopped goes on
  from the tiles it has; a second run that finds a build under way waits
  for it.
- **The Earthdata login, not a token, is the setting** (`EARTHDATA_USERNAME`,
  `EARTHDATA_PASSWORD` in `.env`). The code asks Earthdata Login for the
  account's token, which lasts 60 days, each time it builds, so no token
  expires in `.env`.
- **The lights are warped onto the finest grid**, a strip of rows at a
  time from the COG, and the night layer is finished there after the last
  resample. The cloud layers stay on the infrared grid.
- **The lights are coloured by a curve fitted to CIRA**, on radiance, with
  one colour for unlit land and one for sea (the notes, under "Recipe").
- **All of it is in `georing.lights`**, apart from the Recipe's own code:
  `georing.lights.cog` builds the COG, `georing.lights.layer` reads it into
  the Recipe, and the Recipe only names them.

## Considered Options

- **Black Marble 2016 at 500 m.** NASA's eight tiles of the same picture
  (0.3 to 0.5 GB each, no login). Sharp, but nine years old, and a finished
  picture whose tone curve is unknown.
- **EOG's annual VIIRS night lights (V2.2, 2024).** One global GeoTIFF of
  radiance with background and fires removed; simpler to process. It needs
  an EOG account and is under CC BY 4.0, so the catalogue would have to
  credit EOG; it has no land mask, and its latest year was 2024.
- **VNP46A4, the same product from Suomi-NPP.** The older satellite, near
  the end of its life; NOAA-20 carries on.
- **Live lights from the nightly VIIRS passes.** One pass a night at about
  01:30 local time, with moonlit cloud in it: it does not fit an hourly
  Mosaic.
- **Build the COG into the worker image, as the other static files are.**
  Every image build would download 51 GB or need a place to fetch our own
  COG from, and the build would need the login.
- **Keep the night layer on the infrared grid.** Cheaper, and the lights
  would stay 2 km blobs whatever their source.

## Consequences

- The first Slot after a deployment waits for the build, 20 minutes on a
  home line; its Disks still download meanwhile.
- A new year is a change of `YEAR` in `georing.lights.cog`: the flow builds
  the new COG beside the old one, and each satellite's warp of it is redone.
- NASA asks for no attribution; the catalogue may credit NASA's Black Marble.
- A render now finishes the night layer at 0.5 km: 141 s and 12.2 GB for
  GOES-East (104 s and 11.7 GB before) and 178 s and 21.0 GB for Meteosat
  (170 s and 22.5 GB), with the clouds put together on the infrared grid
  first (the notes, under "satpy", "Memory and time").
