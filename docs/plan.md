# Plan

Agreed in a design session and confirmed by the owner on 2026-11-11. No code
exists yet.

Terms in capitals are defined in `GLOSSARY.md`. Reasons for the four decisions
that were real trade-offs are in `docs/adr/`; this file does not repeat them.

Facts below were looked up on 2026-11-10 and 2026-11-11 from primary sources or
live probes, unless marked *(unverified)* or listed under "Estimates".

## Decisions

### Inputs

- **Satellite set:** GOES-East (GOES-19), GOES-West (GOES-18), Meteosat at 0°
  (MTG-I1, also called Meteosat-12) and Himawari (Himawari-9). The set is a
  setting, so a fifth satellite can be added.
- **Slot:** a full clock hour. A Slot uses each satellite's scan that starts on
  that hour (ADR 0002).
- **No detail is discarded in processing.** The 0.5 km red band is used, so
  Meteosat needs both of its collections (normal and high resolution).

### Products

- **Each Slot publishes five files:** one Mosaic and four Renderings.
- **Rendering:** the satellite's own geostationary projection at native 0.5 km,
  as a COG in lossy WebP at quality 90. Lossless is a setting, for exact
  comparison against GeoColor.
- **Mosaic:** Web Mercator at zoom 8 with 512 px tiles aligned to the web tile
  grid (ADR 0001), lossy WebP at quality 90 (ADR 0004).
- **Recipe:** start from satpy's built-in `geo_color` composite, unchanged, for
  all three sensors. Then tune a Recipe of our own toward GeoColor
  ([Miller et al. 2020](https://journals.ametsoc.org/view/journals/atot/37/3/JTECH-D-19-0134.1.xml))
  on the Comparison scenes. The owner judges when it is close enough.
- **Comparison scenes:** day, night, terminator, sun glint, snow, dust. The
  references are NASA GIBS (`GOES-East_ABI_GeoColor`, `GOES-West_ABI_GeoColor`),
  EUMETView (`mtg_fd:rgb_geocolour`) and CIRA SLIDER (Himawari `geocolor`).
- **Seam:** a narrow feathered band, written in our own code. satpy's
  multi-scene blend is experimental and a wide weighted average shows high
  clouds twice. The width is tuned on real images.
- **Deadline:** a Slot builds as soon as all four Disks are present, typically
  from 14 minutes past the hour. At 35 minutes past it builds without any Disk
  still missing. The measurement behind 35 is under "Data sources, arrival
  times".
- **Missing Disk:** the neighbours fill what they can see and the rest stays
  transparent. The catalogue records which Disks contributed. A Disk that
  arrives later causes the Slot to be rebuilt and replaced. Imagery from
  another Slot is never used as a stand-in, and that includes the same
  satellite's scan at 10 minutes past: a possible later addition for GOES and
  Himawari, ruled out for Meteosat by ADR 0002.

### Flow

- **One Prefect flow per Slot,** with the Slot time as its parameter, scheduled
  at 10 minutes past each hour. The same flow serves backfills and rebuilds.
- **Steps:** per satellite a download step that polls with retries until its
  files exist, then a render step; then one mosaic step; then one index step.
- **At most two renders run at once,** to stay inside the worker's memory.
- **No push notifications.** The AWS and EUMETSAT feeds exist but are not used.

### Catalogue and storage

- **Static STAC,** written as JSON files beside the products: a root
  `catalog.json`; two Collections, `mosaic` and `rendering`; one Item per Slot
  in `mosaic`; one Item per satellite per Slot in `rendering`. Each Mosaic Item
  links to the Renderings it was built from. Items are grouped under one
  catalogue file per day.
- **`latest.json`** names the newest complete Slot, for clients that want only
  that, and so a consumer can tell when the data is stale.
- **Each Item carries the attribution** its data providers ask for.
- **The catalogue is the record of which Slots are done** (ADR 0003).
- **The output location is a URL setting:** a host directory in the compose
  file, an `s3://` bucket (Cloudflare R2) later. Paths start with the product
  and then the date: `mosaic/YYYY/MM/DD/…`, `rendering/YYYY/MM/DD/…`.
- **Retention is the bucket's job:** one lifecycle rule per product prefix,
  Mosaics 7 days and Renderings 2 days. The index step rewrites each
  Collection's list of days from what exists, so no link dangles. In
  host-directory mode the index step itself deletes day folders past retention.
- **Raw downloads** live on the worker's scratch disk and are removed when
  their Slot finishes.

### Hosting and packaging

- **Compose file with two services:** the Prefect server as a single container
  on SQLite with no Redis, and the worker (ADR 0003).
- **Worker size:** 8 cores and 32 GB of RAM, to be raised if the first
  milestone shows it is too small.
- **Python 3.14,** with 3.13 as the fallback. Prefect supports 3.15, but
  `pyresample`, `pykdtree`, `h5py`, `numcodecs` and `bottleneck` publish wheels
  only up to 3.14. satpy 0.60.0's own tests stop at 3.13.
- **`uv`** for dependencies, and one Docker image for the worker. The server
  uses Prefect's official image at the same pinned version.
- **satpy is pinned to a release.** Its static files are fetched when the image
  is built, so a run downloads only satellite data.
- **Settings** live in one YAML file (satellite set, resolution, compression,
  retention, output URL), each overridable by an environment variable.
- **The EUMETSAT key and secret** come from the environment variables
  `EUMETSAT_CONSUMER_KEY` and `EUMETSAT_CONSUMER_SECRET`, kept in a `.env`
  file that git ignores (`.env.example` shows the shape).
- **Deployments** are declared in `prefect.yaml` and registered when the worker
  container starts.
- **Names:** the repository is `georing-mosaic`; the Python package, Docker
  image and bucket prefix are `georing`.
- **Alerting:** none in the first version beyond the Prefect UI.
- **Licence:** private at first; public under MIT once a first Mosaic exists.

### Consumer

satvis reads the Mosaic directly from the bucket. That is a separate change in
the satvis repository; what it needs is under "COG, writing and reading".

## Build order

1. **One Slot as a plain script, without Prefect.** Done when all of these hold:
   - For one daytime Slot and one night-time Slot it writes four Renderings and
     a Mosaic to a directory.
   - It reports, per step, wall time, peak memory, bytes downloaded and output
     file size.
   - The Mosaic's tiles are confirmed aligned to the web tile grid at every
     overview level.
   - It ran on a machine no larger than 8 cores and 32 GB, or the report says
     what size it needed.
   - Each figure under "Estimates" is replaced by its measurement.
2. **Comparison scenes** against the reference products, and the Recipe tuning
   that follows from them.
3. **The Prefect flow and the compose file.**
4. **Backfill.**
5. **The satvis layer,** in the satvis repository.

## Open items

- **EUMETSAT licence.** Confirm the reading in ADR 0002 with EUMETSAT before
  the product is public.
- **Meteosat's late cluster.** Find out whether products stamped near 30 past
  were already downloadable near 14 past: try the download at 15 past on such
  a Slot, or poll the search API for several hours (about one such scan every
  two hours). If they were, nearly every Slot is complete by 17 past and the
  deadline can come down from 35.
- **EUMETSAT account.** The owner will create one; downloads need its key.
- **Overview alignment.** Unconfirmed until checked on a real Mosaic (ADR 0001).
- **Cross-origin range requests on R2.** Whether a public R2 bucket needs extra
  CORS settings for them is unknown.
- **Python 3.14.** Untested with satpy 0.60.0; milestone one will show.
- **The India seam.** Around 70°E both Meteosat and Himawari view the ground at
  about 80° from vertical, so quality there is poor. This is a known limit of
  the first version. The candidates checked and why each fails are under
  "Data sources".

## Data sources

| Position | Satellite | Longitude | Source | Download per Slot, day / night | Ready after scan end | Credentials |
|---|---|---|---|---|---|---|
| GOES-East | GOES-19 | 75.2°W | `s3://noaa-goes19/ABI-L1b-RadF/` | 660 / 270 MB | 10–110 s | none |
| GOES-West | GOES-18 | 137°W | `s3://noaa-goes18/ABI-L1b-RadF/` | 662 / 279 MB | 10–110 s | none |
| Himawari | Himawari-9 | 140.7°E | `s3://noaa-himawari9/AHI-L1b-FLDK/` | 652 / 271 MB | 0.5–4.5 min | none |
| Meteosat 0° | MTG-I1 | 0° | EUMETSAT Data Store, `EO:EUM:DAT:0662` and `EO:EUM:DAT:0665` | 1.03 / 0.47 GB and 1.04 / 0.56 GB | about 4.5 min | key and secret |

The sizes are from one day (2026-11-10), for the bands listed below. All three
buckets are in `us-east-1` and allow anonymous access.

**GOES (ABI)**
- Key: `<YYYY>/<DOY>/<HH>/OR_ABI-L1b-RadF-M6C<bb>_G19_s<YYYYDOYHHMMSSt>_e…_c….nc`,
  one NetCDF file per band per scan (`G18` for GOES-West).
- Bands: C01 blue, C02 red (0.5 km), C03 0.86 µm, C07 3.9 µm, C13 10.3 µm. ABI
  has no green band; the Recipe synthesises it.
- Scans start at 20 seconds past each 10 minutes. C02 arrives last.
- `ABI-L2-MCMIPF` holds all bands in one 369 MB file at 2 km. It is not used,
  because it discards detail.

**Himawari (AHI)**
- Key: `<YYYY>/<MM>/<DD>/<HHMM>/HS_H09_<YYYYMMDD>_<HHMM>_B<bb>_FLDK_R<rr>_S<ss>10.DAT.bz2`.
  Ten segments per band.
- Bands: B01 blue, B02 green, B03 red (0.5 km), B04 0.86 µm, B07 3.9 µm,
  B13 10.4 µm: 60 files.
- No scans exist at 02:40 and 14:40. Hourly Slots never use them.

**Meteosat 0° (FCI)**
- `0662` is the normal-resolution collection (1 km visible, 2 km infrared, all
  16 channels). `0665` is the high-resolution one (four channels, including
  0.5 km red). Both are needed.
- One scan is 40 body chunks plus one trailer per collection. Every chunk holds
  every channel, so there is no per-band download.
- Sensing runs from 7 seconds past to 9 minutes 23 seconds past.
- Client: `eumdac` 3.1.1. Search is anonymous; download needs a bearer token
  from a consumer key and secret (`https://api.eumetsat.int/api-key/`).
- Rate limits exist (the client handles HTTP 429) but are not published.

**Arrival times**

Measured over 720 hourly Slots, 2026-10-11 to 2026-11-10: minutes past the
hour at which the on-the-hour scan was complete. For the buckets this is the
latest `LastModified` among the needed files; for Meteosat it is the product's
`updated` time in the anonymous search API, which a live poll showed to be
within a minute of the product first appearing. No download with a token was
attempted.

| Source | Median | 99th percentile | Slots with no on-the-hour scan |
|---|---|---|---|
| GOES-East | 10.9 | 11.6 | 1 |
| GOES-West | 10.9 | 11.6 | 1 |
| Himawari | 13.9 | 16.8 | 2 |
| Meteosat, both collections | 14.2 | 31.3 | 1 |

- All four were complete by 15 past in 85% of Slots, by 20 past in 90%, by
  30 past in 93% and by 45 past in 98.5%.
- Meteosat's `updated` times fall in two clusters: about nine Slots in ten near
  14 past, most of the rest near 30 past. The 99th percentile of the joint time
  is 31.5, which is why the deadline is 35 and not 30.
- Whether the later cluster is a first publication or a re-publication of a
  product already downloadable near 14 past is unknown: `updated` keeps only
  the latest value. See "Open items".
- Rare long delays exist: two Meteosat Slots many hours late, one Himawari
  Slot at 101 minutes past.
- Wherever a satellite had no on-the-hour scan, its scan at 10 past existed.

**Licences and attribution**
- GOES: open; NOAA asks for attribution and no implied endorsement.
- Himawari: JMA data distributed by NOAA; both ask for attribution.
- Meteosat: see ADR 0002. Images made from the data are our own; the required
  line is "[Contains modified] EUMETSAT Meteosat data [year]".

**Satellites considered for the India seam, and rejected**
- Meteosat-9 at 45.5°E: its instrument has no blue or green band.
- GK2A at 128.2°E (`s3://noaa-gk2a-pds`): open, with real colour bands, but too
  far east to help, 12 to 14 minutes slower, and satpy has no `geo_color` for it.
- FY-4B at 105°E: data needs a real-name account with order-based pickup, and
  WMO's registry says its imager failed on 30 July 2026.
- INSAT and Electro-L: no open download found.

Sources:
[AWS GOES](https://registry.opendata.aws/noaa-goes/),
[AWS Himawari](https://registry.opendata.aws/noaa-himawari/),
[EUMETSAT Data Policy](https://www-cdn.eumetsat.int/files/2026-01/45173%20-%20Data_Policy.pdf),
[eumdac](https://pypi.org/project/eumdac/),
[WMO OSCAR](https://space.oscar.wmo.int/satellites).

## satpy

Version 0.60.0 (2026-03-04). The companion versions are pyresample 1.35.0,
pyspectral 0.14.3 and pyorbital 1.14.0.

**The `geo_color` composite**
- It exists for `abi`, `ahi` and `fci` only, with the same structure in each:
  a day layer and a night layer blended between 78° and 88° solar zenith. The
  night layer is high clouds over low clouds over a city-lights image.
- The day layers differ in how green is made: `true_color` with a simulated
  green for ABI, a hybrid of the real green and the near-infrared for AHI and
  FCI. Check the Seams for a colour step.
- A Recipe of our own goes in a composite YAML file under `SATPY_CONFIG_PATH`
  *(unverified: inferred from how satpy loads composites)*.
- [Issue #3397](https://github.com/pytroll/satpy/issues/3397) proposes a
  different sun-angle correction for the built-in composites, so the look may
  change between releases.

**Static files, fetched at image build**
- `BlackMarble_2016_3km_geo.tif`, 64.4 MB, the city lights. **satpy 0.60.0
  cannot download it**: NASA moved the file. The working URL is
  `https://assets.science.nasa.gov/content/dam/science/esd/eo/images/imagerecords/144000/144898/BlackMarble_2016_3km_geo.tif`.
  Place it at `<data_dir>/composites/StaticImageCompositor/` and set
  `SATPY_DOWNLOAD_AUX=False` *(unverified: inferred from the source)*.
- `gshhs_land_water_mask_3km_i.tif`, 0.5 MB, from
  `https://zenodo.org/records/10076199/files/`.
- The rest: `satpy_retrieve_all_aux_data --data-dir <dir> --composite-sensors abi ahi fci`.
- Rayleigh tables: `download_atm_correction_luts.py -a rayleigh_only` (54 MB)
  and `download_rsr.py` (5 MB). Point pyspectral at them with a YAML file named
  by `PSP_CONFIG_FILE`, and set `download_from_internet: False` in it.

**Readers**
- `abi_l1b` for GOES.
- `ahi_hsd` for Himawari. It decompresses each `.bz2` segment to a temporary
  file, with `pbzip2` if that is on the path. Allow scratch space for it.
- `fci_l1c_nc` for Meteosat, given both collections' files together. The data
  is compressed: `import hdf5plugin` before reading, or the read fails with
  "NetCDF: Filter error".

**Memory and time**
- Computing the sun and satellite angles dominates memory.
- `scn.load([...], generate=False)` before resampling saves time and memory for
  composites that mix resolutions. With `geo_color` this can fail after one
  resample ([issue #2733](https://github.com/pytroll/satpy/issues/2733));
  resampling twice worked there.
- Settings: dask `array.chunk-size` of `32MiB`, `DASK_NUM_WORKERS` 4 to 8,
  `OMP_NUM_THREADS=1`, and a raised `GDAL_CACHEMAX`.
- Maintainers report about 6 GB and under 140 s for a full-disk ABI
  `true_color`, and 260 to 290 s for AHI with four workers
  ([issue #1902](https://github.com/pytroll/satpy/issues/1902)). No published
  figure exists for `geo_color`.

**Joining satellites**
- `satpy.modifiers.angles.get_satellite_zenith_angle` gives the view angle the
  Seam is placed by.
- A worked ring example, with weights `(1 - (satz/90)^2)^2`, is in
  [issue #2758](https://github.com/pytroll/satpy/issues/2758#issuecomment-2767072725).
  Its lesson: resample with `reduce_data=False`.
- For geostationary-to-grid resampling the maintainers recommend
  `gradient_search`. `native` only changes resolution by whole factors.

**Output**
- The `geotiff` writer takes `driver="COG"` and passes GDAL's COG options
  through. satpy has no web-tile writer.

## Prefect

Version 3.9.2 (2026-11-06). Pin the server image, the worker image and the
client to one version: a client newer than a self-hosted server is unsupported.

**Compose**
- A single `prefect server start` container runs the API and the background
  services in one process and needs no Redis *(unverified: inferred from the
  default in-memory broker; the official compose file splits them and adds
  Redis)*.
- Official guide: <https://www.prefect.io/docs/v3/how-to-guides/self-hosted/docker-compose>.
- Images: `prefecthq/prefect:3.9.2-python3.14`.
- The worker needs `PREFECT_API_URL=http://<server>:4200/api`. Leave
  `PREFECT_API_KEY` unset against a self-hosted server, or requests fail
  with 401.
- `prefect worker start --pool <name> --type process` creates the pool if it
  is missing.

**Deployments**
- `prefect --no-prompt deploy --all` registers what `prefect.yaml` declares.
- Set the `pull` step explicitly
  (`prefect.deployments.steps.set_working_directory`). Left out, Prefect
  records the deploying machine's current directory.
- A deployment `concurrency_limit` with `CANCEL_NEW` can cancel the next
  scheduled run, because a slot is taken as soon as a run is pending.

**Inside the flow**
- Retries: `@task(retries=…, retry_delay_seconds=exponential_backoff(…))`.
- The two-renders limit: a global concurrency limit
  (`prefect gcl create <name> --limit 2`) taken with
  `with concurrency("<name>")`. It is coordinated by the server, so it holds
  across processes.
- One run per Slot: `run_deployment(..., idempotency_key=…)`. Flow run names
  are not unique.
- Task caching does nothing unless result persistence is on, and the default
  cache key includes the run id, so it never matches across runs.
- Prefect gives no guidance on plain dask `.compute()` inside a task. Treat
  the combination as untested.

**Housekeeping**
- Self-hosted, flow runs and logs are kept forever unless
  `PREFECT_SERVER_SERVICES_DB_VACUUM_ENABLED="events,flow_runs"` is set.
- On Prefect Cloud every log line counts toward a rate limit.

## COG, writing and reading

**Writing (GDAL COG driver; rasterio 1.5.2 bundles GDAL 3.12.2 with WebP)**
- `TILING_SCHEME=GoogleMapsCompatible` reprojects to Web Mercator and aligns
  tiles at the chosen zoom. `ZOOM_LEVEL=8`, `BLOCKSIZE=512`.
- `ALIGNED_LEVELS` sets how many overview levels are aligned to the grid. A
  whole-world image may align at every level without it *(unverified)*: check
  with `gdalinfo`.
- `COMPRESS=WEBP`, `QUALITY=90`. `QUALITY=100` switches to lossless. WebP needs
  exactly 3 or 4 bands of 8 bits.
- `ADD_ALPHA` defaults to yes when reprojecting, and WebP stores the alpha
  inside each tile.
- `NUM_THREADS` compresses tiles in parallel.
- `SPARSE_OK` writes empty tiles with a byte count of zero, which readers must
  handle.
- JPEG XL cannot be written with the pip wheels, only with a conda-built GDAL.

**Reading in satvis (a later change, in that repository)**
- Web: Cesium has no COG support. Write a small imagery provider on
  `@cogeotiff/core` (9 kB gzipped): `getTile(x, y)` returns the tile's bytes
  and type from one range request. Model the time handling on
  `src/modules/GibsTimeLayer.ts`, with an hourly step.
- iOS: the native renderer has no COG reader. It needs a TIFF header parser, a
  tile source that yields a URL plus a byte range (today
  `ios/SatvisKit/Sources/SatvisRender/Imagery.swift` yields a URL only), and a
  fetcher that accepts a 206 answer (today
  `ios/SatvisKit/Sources/SatvisData/TileFetcher.swift` requires 200). Its time
  handling is daily-only and must become hourly. iOS decodes WebP from
  version 14.

## Estimates

None of these is measured. Milestone one replaces them.

- A daytime Slot is about 4 GB of download: the sum of the one-day sizes in
  the table above.
- A Mosaic is under 1 GB. A lossless Rendering is about 600 MB.
- Unpruned output is 25 to 50 GB per day.
- Encoding a Mosaic in WebP takes about 19 core-minutes.
- The header a client fetches per Mosaic is under 200 kB with 512 px tiles.
- Lossy WebP is 25 to 35% smaller than JPEG at the same quality, from
  natural-photo studies.
