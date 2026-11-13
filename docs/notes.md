# Notes

What was looked up and measured while building this: the data sources, how
satpy, Prefect and the COG driver behave, and what a Slot costs. The decisions
that rest on these are in [plan.md](plan.md); this file is the evidence.

Facts were looked up on 2026-11-10 to 2026-11-12 from primary sources or live
probes. Terms in capitals are defined in
`GLOSSARY.md`.

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
- Key:
  `<YYYY>/<DOY>/<HH>/OR_ABI-L1b-RadF-M6C<bb>_G19_s<YYYYDOYHHMMSSt>_e…_c….nc`,
  one NetCDF file per band per scan (`G18` for GOES-West).
- Bands: C01 blue, C02 red (0.5 km), C03 0.86 µm, C07 3.9 µm, C13 10.3 µm. ABI
  has no green band; the Recipe synthesises it.
- Scans start at 20 seconds past each 10 minutes. C02 arrives last.
- `ABI-L2-MCMIPF` holds all bands in one 369 MB file at 2 km. It is not used,
  because it discards detail.

**Himawari (AHI)**
- Key:
  `<YYYY>/<MM>/<DD>/<HHMM>/HS_H09_<YYYYMMDD>_<HHMM>_B<bb>_FLDK_R<rr>_S<ss>10.DAT.bz2`.
  Ten segments per band.
- Bands: B01 blue, B02 green, B03 red (0.5 km), B04 0.86 µm, B07 3.9 µm,
  B13 10.4 µm: 60 files.
- No scans exist at 02:40 and 14:40. Hourly Slots never use them.

**Meteosat 0° (FCI)**
- `0662` is the normal-resolution collection (1 km visible, 2 km infrared, all
  16 channels). `0665` is the high-resolution one (four channels, including
  0.5 km red). Both are needed.
- One scan is 40 body chunks plus one trailer per collection. Every chunk holds
  every channel, so there is no per-band download. satpy cannot open the
  trailer, so only the 80 body chunks are downloaded.
- Sensing runs from 7 seconds past to 9 minutes 23 seconds past.
- Client: `eumdac` 3.1.1. Search is anonymous; download needs a bearer token
  from a consumer key and secret (`https://api.eumetsat.int/api-key/`).
- Rate limits exist (the client handles HTTP 429) but are not published. Four
  downloads at once fetched a scan in 67 to 78 s without a refusal.

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
  the latest value. See "Open items" in the plan.
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
- GK2A at 128.2°E (`s3://noaa-gk2a-pds`): open, with real colour bands, but
  too far east to help, 12 to 14 minutes slower, and satpy has no `geo_color`
  for it.
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
- A Recipe of our own goes in composite and enhancement YAML files in a
  directory named by `SATPY_CONFIG_PATH`. satpy merges them with its own, so
  ours can name satpy's composites and modifiers.
- EUMETView's `mtg_fd:rgb_geocolour` is this composite: it differs from our
  render of `geo_color` by 1.5 levels of 255 on average. It is therefore no
  independent reference. NASA GIBS carries CIRA's GeoColor for GOES regridded
  to lat/lon; SLIDER carries it for all four satellites, unregridded.
- The night layer needs two static images that sit on their own lat/lon
  grids, so a plain `load` leaves `geo_color` unmade
  ([issue #2733](https://github.com/pytroll/satpy/issues/2733)). The render
  warps both onto the satellite's coarsest band grid once, keeps them under
  `<work_dir>/grids/`, finishes the night layer there, and only then resamples to
  0.5 km. The night layer is therefore 2 km data for GOES and Himawari and
  1 km for Meteosat, as the infrared bands are.
- [Issue #3397](https://github.com/pytroll/satpy/issues/3397) proposes a
  different sun-angle correction for the built-in composites, so the look may
  change between releases.

**Recipe**

The Comparison scenes come in two sets. The **tuning set** (2026-11-10) is
what curves are read off and what changes are looked at. The **holdout set**
(2026-09-14, the oldest day SLIDER still held for all four satellites on
2026-11-11, at places no tuning scene covers) is only measured: no parameter
is fitted to it or adjusted against it by eye. `georing-compare --set
holdout` runs it alone. The figures are the mean absolute difference from
CIRA's GeoColor per channel (red, green, blue), in levels of 255, for
satpy's `geo_color`, for the Recipe before it was tuned and for the Recipe
now.

| Scene | Set | Satellite, UTC | Place | `geo_color` | Before tuning | Recipe |
|---|---|---|---|---|---|---|
| day | tuning | GOES-East, 18:00 | Florida, Cuba, the Bahamas | 10, 15, 17 | 4, 6, 5 | 4, 6, 5 |
| night | tuning | GOES-East, 06:00 | the eastern United States | 27, 23, 26 | 25, 22, 23 | 8, 6, 7 |
| terminator | tuning | Meteosat, 18:00 | West Africa and the Atlantic at dusk | 16, 26, 44 | 10, 13, 18 | 9, 10, 12 |
| glint | tuning | GOES-West, 18:00 | the Pacific at 9°S 115°W | 9, 15, 18 | 2, 3, 3 | 2, 3, 3 |
| snow | tuning | Himawari, 06:00 | Mongolia and Lake Baikal | 16, 16, 19 | 8, 10, 13 | 7, 9, 12 |
| dust | tuning | Meteosat, 11:00 | the Sahara around Lake Chad | 15, 13, 18 | 3, 4, 6 | 3, 4, 5 |
| day-ahi | tuning | Himawari, 06:00 | Australia and the Coral Sea | 9, 11, 13 | 3, 5, 5 | 2, 4, 5 |
| day-fci | tuning | Meteosat, 11:00 | the Gulf of Guinea and central Africa | 14, 17, 23 | 3, 5, 5 | 3, 5, 5 |
| night-warm | tuning | Meteosat, 00:00 | the Sahara and the Sahel | 30, 37, 43 | 35, 45, 56 | 3, 3, 3 |
| dawn | tuning | GOES-East, 11:00 | the Caribbean and Venezuela | 11, 19, 25 | 16, 13, 15 | 11, 11, 12 |
| glint-ahi | tuning | Himawari, 02:00 | around New Guinea | 7, 8, 9 | 3, 4, 6 | 3, 4, 5 |
| storms | tuning | Meteosat, 00:00 | thunderstorms over the Congo basin | 35, 29, 39 | – | 6, 6, 8 |
| storms-east | tuning | Meteosat, 18:00 | thunderstorms over Tanzania and Lake Victoria | 23, 20, 24 | – | 5, 5, 5 |
| h-day-ahi | holdout | Himawari, 03:00 | Borneo, Java and Sulawesi | 8, 10, 10 | 3, 7, 8 | 2, 6, 7 |
| h-day-fci | holdout | Meteosat, 12:00 | Iberia, Morocco, the western Mediterranean | 10, 11, 26 | 2, 5, 8 | 2, 4, 8 |
| h-night-cold | holdout | GOES-East, 08:00 | the Pampas at the end of winter | 39, 36, 41 | 36, 37, 40 | 5, 6, 6 |
| h-night-warm | holdout | Meteosat, 01:00 | Libya and Egypt | 22, 27, 31 | 26, 34, 42 | 4, 3, 3 |
| h-dawn | holdout | Himawari, 22:00 | Korea, Japan, the East China Sea | 18, 22, 26 | 17, 20, 23 | 12, 16, 18 |
| h-dusk | holdout | GOES-East, 22:00 | Brazil and Bolivia | 20, 14, 24 | 13, 13, 17 | 6, 6, 8 |
| h-snow | holdout | GOES-East, 15:00 | the Andes at the end of winter | 8, 7, 16 | 3, 9, 4 | 3, 7, 4 |
| h-glint | holdout | Himawari, 22:00 | the central Pacific near 4°N 170°E | 13, 17, 22 | 6, 9, 10 | 6, 9, 10 |

Exact figures are in `difference.json` beside the images. The dust and day-fci
scenes are at 11:00 because SLIDER has no Meteosat image for 12:00 on
2026-11-10. The storm scenes were added during the tuning; before the cloud
layer's ramp was changed, they were 17.5, 18.1, 17.4 and 12.7, 12.9, 12.2.
Over the water of the Great Bahama Bank (79.5–77.5°W, 23–25.5°N) the day
scene's mean colour is 44, 84, 105 against CIRA's 43, 90, 107; before tuning
it was 44, 81, 106.

Render cost on eight cores, from the Slot builds of 2026-11-10 18:00 and
06:00 after the cloud-top step was taken out: GOES-East 185 and 169 s,
10.8 and 12.0 GB at peak; GOES-West 183 and 165 s, 10.3 and 12.2 GB;
Himawari 249 and 231 s, 12.1 and 11.8 GB; Meteosat 272 and 275 s, 21.6 and
21.3 GB.

What the Recipe changes from `geo_color`:
- **One day layer for all three sensors.** FCI's extra darkening toward the
  terminator (`sunz_reduced`) is dropped, so the sensors agree at a Seam.
- **The sun-angle normalisation stops growing at 80°** (`georing_sunz`;
  satpy's stops at 88°). Toward the terminator the day layer darkens as
  CIRA's does, and the Rayleigh correction, which does not shrink with it,
  warms the tone. Tried at 78, 81, 82, 84 and 88°: 80 is best on both
  terminator scenes.
- **Rayleigh correction fades out toward the terminator,** from full at a sun
  angle of 70° to a tenth at 88°. At full strength it takes out more blue than
  a low sun puts in, and dusk turns olive.
- **No reduction of the Rayleigh correction above cold cloud tops.** CIRA
  reduces it there (Miller et al. 2020, section 5a1), and a version of that was
  tried: it bought about 3 levels of blue on the snow scene and cost the day
  scene about 1. It was taken out because it re-implemented 75 lines of a satpy
  internal for that gain, and the goal is a consistent global look, not CIRA
  by the level.
- **ABI's green leans toward blue:** 0.565 blue, 0.365 red, 0.07 near
  infrared, where satpy splits 0.465 and 0.465. CIRA synthesises AHI's
  0.51 µm green, which lies nearer blue than red. Shallow water on sand turns
  closer to CIRA's turquoise.
- **A tone curve per channel and sensor** after satpy's stretch. The curves
  were fitted once, from the high-sun tuning scenes rendered without them: for
  each level, the median level CIRA shows where ours shows that level. The
  tool that did it was not kept. ABI is read off day and glint, AHI off
  day-ahi and glint-ahi, FCI off day-fci and dust. From level 140 up the three
  share one curve read off all of them, so bright cloud matches at a Seam.
  Below, FCI's blue is lifted most: satpy over-corrects its 0.44 µm band.
- **The infrared cloud layer is white**, opaque by its temperature
  (`georing_high_clouds`): CIRA draws it white (Miller et al. 2020, Eq. 8),
  `geo_color` greys it by temperature too, which left cold clear ground and
  low cloud dark. This is what makes cold ground lighter by night. The
  opacity ramps linearly from 296 K down to 185 K in the tropics and 205 K
  poleward of 60° (satpy's ramp ends at 210/230 K), read off the night pixels
  of the night, night-warm, storms and storms-east scenes. Over storm tops
  CIRA is brighter the colder the top, by about 1.6 levels per kelvin all the
  way to 185 K (195 at 205 K, 227 at 185 K). So only the coldest tops are
  opaque and deep convection keeps its shading; with satpy's ramp everything
  below 210 K was flat white.
- **The low-cloud layer starts at 0 K over land on every sensor**
  (`georing_low_clouds`). `geo_color` starts it at 1.5 K for FCI. Dry ground
  emits less at 3.9 µm, so CIRA tints it bluish-lilac by night; the Recipe now
  does too, which fixed both warm-ground night scenes.
- **City lights recoloured by brightness:** sea black, unlit land dark purple,
  lights amber, deepening from the fringes to the cores. The colours are the
  median CIRA shows over clear land of the night tuning scenes, per
  brightness, once its infrared layer is taken off.

What still differs from CIRA:
- **Thick cold cloud by night** keeps its shading, but its coldest cores
  are a little brighter than CIRA's (storms: 8 levels in blue): ours are
  white, 255, from 185 K down, where CIRA's reach about 227.
- **The terminator.** Tuning dusk 12.3, dawn 12.1, holdout dawn 18.1 (blue
  worst). On the tuning scenes ours is too bright at sun angles near 74° at
  dawn, too dark near 82°, and short of blue over clear sea at 66–72° at dusk.
  No single setting of the sun-angle limit, the Rayleigh fade or the day/night
  blend (tried: fade strength 0, 0.5, 0.6, fade ending at 84°, blend 76–86,
  80–87, 82–90, 84–92) improves both. CIRA's 2025 update changed its
  twilight blend; how is not published.
- **Sun glint on Himawari** (holdout 10.3): ours is 6 to 10 levels darker over
  the glint than CIRA's, and greyer. The AHI glint tuning scene shows no such
  difference.
- **Vegetation on Himawari** is greener and more saturated than CIRA's (New
  Guinea in glint-ahi): the hybrid green, as satpy makes it.
- **Shallow water** is still bluer than CIRA's turquoise, though its mean is
  within 6 levels.
- **City lights are coarser:** the Black Marble image is 3 km and the night
  layer is finished on the infrared grid.
- **Snow on Himawari** (tuning 12.2): dry ground is too blue, and high cloud
  is greyer than CIRA's since the cloud-top step was taken out.

**Static files, fetched at image build**
- `BlackMarble_2016_3km_geo.tif`, 64.4 MB, the city lights. **satpy 0.60.0
  cannot download it**: NASA moved the file. The working URL is
  `https://assets.science.nasa.gov/content/dam/science/esd/eo/images/imagerecords/144000/144898/BlackMarble_2016_3km_geo.tif`,
  and the file there matches satpy's checksum. Place it at
  `<data_dir>/composites/` and set `SATPY_DOWNLOAD_AUX=False`. The Recipe
  names both static images by file; their URLs and checksums are in
  `georing.static` only.
- `gshhs_land_water_mask_3km_i.tif`, 0.5 MB, from
  `https://zenodo.org/records/10076199/files/`, into the same directory.
- `georing-static` fetches both, and pyspectral's Rayleigh tables (54 MB)
  and spectral responses (5 MB), and points pyspectral at them offline.

**Readers**
- `abi_l1b` for GOES.
- `ahi_hsd` for Himawari. It decompresses each `.bz2` segment to a temporary
  file, with `pbzip2` if that is on the path. Allow scratch space for it.
- `fci_l1c_nc` for Meteosat, given both collections' files together. The data
  is compressed: `import hdf5plugin` before reading, or the read fails with
  "NetCDF: Filter error". It takes the infrared bands from the high-resolution
  collection, at 1 km.

**Memory and time**
- Computing the sun and satellite angles dominates memory.
- `scn.load([...], generate=False)` before resampling saves time and memory for
  composites that mix resolutions, but not for `geo_color`: its cloud
  compositors build whole-Disk arrays in memory, so making the night layer at
  0.5 km cost 23 to 28 GB per render. Made on the infrared grid it costs 11 GB.
- satpy's `gradient_search` returns the static images in other chunks than the
  bands have, which also holds the whole Disk in memory. The render warps them
  with GDAL and reads them back in the bands' chunks.
- Settings: dask `array.chunk-size` of `32MiB`, `DASK_NUM_WORKERS` 4 to 8,
  `OMP_NUM_THREADS=1`, and a raised `GDAL_CACHEMAX`.
- Maintainers report about 6 GB and under 140 s for a full-disk ABI
  `true_color`, and 260 to 290 s for AHI with four workers
  ([issue #1902](https://github.com/pytroll/satpy/issues/1902)). No published
  figure exists for `geo_color`.

**FCI**
- satpy keeps FCI's rows in the order they are stored, south first, and
  writes a GeoTIFF with a positive pixel height. The georeferencing is right,
  and GDAL warps it onto the Mosaic's grid either way; only a reader that
  goes by row order would show it upside down.

**Python 3.14**
- The FCI reader hands its open NetCDF files to dask without a lock. With
  netCDF4 1.7.5 on HDF5 2.2 a threaded read fails with "NetCDF: HDF error";
  a single-threaded read works. The render replaces the reader's one method
  with a locked copy.
- A raster opened lazily through rioxarray 0.24 prints "Error in
  sys.excepthook" when the interpreter exits. Nothing is wrong; a step's
  process skips interpreter teardown to keep the log clean.

**What a render prints**
- satpy and its libraries print the same six lines on every render. Each was
  traced to its cause on a night-time GOES-East Disk on 2026-11-13, and none
  changes the image, so the render filters exactly these (`KNOWN_WARNINGS` and
  `KNOWN_LOG_LINES` in `georing.render`) and shows whatever else is said.
- "The following datasets were not created and may require resampling": satpy,
  twice, because the render loads the Recipe in two stages.
- "No sensor name specified in HDF5 file": pyspectral, reading a sensor's
  response file for the Rayleigh correction.
- "divide by zero" and "invalid value" in `trollimage/xrimage.py`: satpy's own
  low-cloud enhancement colours with a one-colour palette, and trollimage
  works out a scale for its metadata from it.
- "The specified chunks separate the stored chunks": xarray, when satpy opens
  the two static images. They are read once; the warped copies are kept.
- "cannot convert float NaN to integer": satpy's image reader, on a static
  image that declares no nodata value. It leaves the data unmasked, which is
  what the Recipe wants.
- "invalid value encountered in log": the 3.9 µm brightness temperature is NaN
  where the radiance is negative. That was 477 of 23 million pixels, all on
  cold cloud tops (median 200 K at 10.4 µm), and the night layer shows them as
  white high cloud. The night layer's only NaN pixels, 44 of them, lie exactly
  on the Disk's rim, which the join cuts off.

**Joining satellites**
- The Mosaic computes each satellite's view angle on its own grid, from the
  longitude and height in the Rendering's projection and a spherical Earth.
  `satpy.modifiers.angles.get_satellite_zenith_angle` gives the same angle,
  but only on a Disk's grid.
- The Renderings are warped to the Mosaic grid with GDAL (bilinear), in
  2048 px chunks, and not with satpy's resamplers.

**Output**
- The `geotiff` writer takes `driver="COG"` and passes GDAL's COG options
  through. satpy has no web-tile writer.

## Prefect

Version 3.9.2 (2026-11-06). Pin the server image, the worker image and the
client to one version: a client newer than a self-hosted server is unsupported.

**Compose**
- A single `prefect server start` container runs the API and the background
  services in one process on SQLite and needs no Redis: in ours the schedule
  fires, queued runs start and priorities between work queues hold. The
  official compose file splits them and adds Redis.
- Official guide: <https://www.prefect.io/docs/v3/how-to-guides/self-hosted/docker-compose>.
- Images: `prefecthq/prefect:3.9.2-python3.14`.
- The worker needs `PREFECT_API_URL=http://<server>:4200/api`. Leave
  `PREFECT_API_KEY` unset against a self-hosted server, or requests fail
  with 401.
- `prefect worker start --pool <name> --type process` creates the pool if it
  is missing. `worker.sh` creates it earlier, before `prefect deploy`, and
  the `catch-up` queue with it. `--limit 1` makes the worker take one flow
  run at a time.
- `python:3.14-slim` lacks `libexpat1`, which rasterio's wheel loads. The
  image build imports the stack once, so a missing library fails the build.

**Deployments**
- `prefect --no-prompt deploy --all` registers what `prefect.yaml` declares.
- Set the `pull` step explicitly
  (`prefect.deployments.steps.set_working_directory`). Left out, Prefect
  records the deploying machine's current directory.
- A deployment `concurrency_limit` with `CANCEL_NEW` can cancel the next
  scheduled run, because a slot is taken as soon as a run is pending.

**Inside the flow**
- One run per Slot: `run_deployment(..., idempotency_key=…)`. Flow run names
  are not unique. The key names the Slot and the Disks it would add, so the same
  rebuild is queued once and a later, different one still can be. `work_queue_name=` puts the run in a queue
  other than the deployment's.
- A task that fails after its retries does not have to fail the flow:
  `future.result(raise_on_failure=False)` returns the exception. That is how
  a Disk that never arrives becomes a missing Disk.
- `prefect.testing.utilities.prefect_test_harness` runs flows against a
  temporary database; `tests/test_flow.py` uses it with the heavy steps faked.
- Prefect gives no guidance on plain dask `.compute()` inside a task. We do
  not combine them: a task starts a child process that does the computing.

**Housekeeping**
- Self-hosted, flow runs and logs are kept forever unless
  `PREFECT_SERVER_SERVICES_DB_VACUUM_ENABLED="events,flow_runs"` is set. The
  default is `events` only, and what is pruned is older than 90 days.
- On Prefect Cloud every log line counts toward a rate limit.

## COG, writing and reading

**Writing (GDAL COG driver; rasterio 1.5.2 bundles GDAL 3.12.2 with WebP)**
- `TILING_SCHEME=GoogleMapsCompatible` reprojects to Web Mercator and aligns
  tiles at the chosen zoom. `ZOOM_LEVEL` counts tiles of `BLOCKSIZE`: with
  `BLOCKSIZE=512`, level 8 is 131,072 px across at 306 m. The Mosaic is
  `ZOOM_LEVEL=7`, `BLOCKSIZE=512`: 65,536 px at 611 m.
- A whole-world image aligns at every overview level without `ALIGNED_LEVELS`.
  Checked on both test Mosaics: eight levels from 65,536 px down to one tile,
  each starting at the grid's corner. `encode_mosaic` repeats the check on
  every Mosaic and fails if a level is off.
- A tile read by byte range is a complete WebP image with its own alpha, and
  decodes to the same pixels GDAL returns. Checked at four levels.
- `BIGTIFF=NO` for the Mosaic: a BigTIFF tile index is half as large again.
- `COMPRESS=WEBP`, `QUALITY=90`. `QUALITY=100` switches to lossless. WebP needs
  exactly 3 or 4 bands of 8 bits.
- `ADD_ALPHA` defaults to yes when reprojecting, and WebP stores the alpha
  inside each tile.
- `NUM_THREADS` compresses tiles in parallel.
- `SPARSE_OK` writes empty tiles with a byte count of zero, which readers must
  handle. A transparent tile that was written is a WebP image of about 900
  bytes.
- JPEG XL cannot be written with the pip wheels, only with a conda-built GDAL.

**Reading in satvis (a later change, in that repository)**
- The timeline comes from `mosaic/collection.json` alone: each `rel: "item"`
  link has `datetime`, the Slot, equal to its Item's `properties.datetime`.
  Before 2026-11-13 the Slot had to be read off the file name
  (`georing_mosaic_20261113T1500Z.json`), and satvis falls back to that while
  the field is missing. Fetching every Item instead costs one request per
  Slot kept: 168 for a week.
- A Mosaic's file is replaced under the same name when its Slot is rebuilt for
  a late Disk, and the new file's tiles lie at other offsets. A reader must
  not use a header on a file it was not read from: it sends `If-Match` with
  the ETag it got with the header on every tile request, and reads the header
  again when the answer is 412. R2 answers so through its S3 interface
  (checked on 2026-11-12); its public address is not checked.
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

## Measurements

From two Slots, 2026-11-10 18:00 and 06:00 UTC, built on 2026-11-11 with
Python 3.14.7. The machine has 32 threads (AMD Ryzen 9 5950X) and 126 GB.
Every step was pinned to 8 of them, the steps ran one after another, and a
cgroup capped the whole run at 32 GB.

No Slot is daytime for all four satellites. At 18:00 both GOES are in daylight
and Meteosat is half lit; at 06:00 Himawari is in daylight and Meteosat is
half lit.

| Step | Wall, s | CPU, s | Peak memory, GB | Download, MB | Output, MB |
|---|---|---|---|---|---|
| download GOES-East | 18 / 10 | 5 / 2 | 0.1 | 653 / 270 | |
| render GOES-East | 179 / 155 | 1092 / 1018 | 11.1 / 10.9 | | 159 / 30 |
| download GOES-West | 18 / 14 | 5 / 3 | 0.1 | 628 / 323 | |
| render GOES-West | 176 / 157 | 1085 / 1015 | 11.5 / 11.5 | | 140 / 36 |
| download Himawari | 15 / 21 | 3 / 4 | 0.1 | 346 / 548 | |
| render Himawari | 255 / 240 | 1509 / 1317 | 12.3 / 12.0 | | 42 / 111 |
| download Meteosat | 67 / 72 | 7 / 7 | 0.1 | 1701 / 1805 | |
| render Meteosat | 279 / 277 | 1804 / 1804 | 20.6 / 21.0 | | 83 / 72 |
| mosaic join | 161 / 160 | 1217 / 1214 | 5.0 | | |
| mosaic encode | 220 / 213 | 627 / 604 | 0.3 | | 371 / 277 |
| **Slot** | **1389 / 1322** | **7353 / 6988** | **20.6 / 21.0** | **3327 / 2946** | **794 / 525** |

Each cell is the 18:00 Slot, then the 06:00 Slot. The table is from the first
build, with satpy's `geo_color`, a Seam of 0.5° and four published Renderings:
a render's time includes writing its Rendering, 21 to 39 s, and its output is
that Rendering.

What holds now, with the Recipe, the 5° Seam and only the Mosaic published:

- A Slot takes about 17 minutes on 8 cores. The 23:00 Slot of 2026-11-11,
  built from a shell on 2026-11-13, took 16 min 45 s: the four renders 145 to
  238 s each, the join 171 s and the encode 64 s.
- A render peaks at 10 to 12 GB, Meteosat's at 20 to 22 GB; the join at 5 GB.
  These were measured before the measuring of each step was removed.
- A Slot is 2.9 to 3.3 GB of download and a Mosaic of 280 to 420 MB: 405 to
  420 MB for the evening Slots of 2026-11-11, 282 to 361 MB for the eleven
  Slots from 03:00 to 13:00 on 2026-11-13. That is 7 to 10 GB a day; a whole
  day has not been added up. Nothing prunes a directory.
- Encoding a Mosaic in WebP takes 64 s. Until 2026-11-13 it took 2.8 minutes:
  `rasterio.Env(GDAL_CACHEMAX=2048)` sets GDAL's block cache to 2048 bytes,
  not megabytes, where the environment variable `GDAL_CACHEMAX=2048` means
  2 GB. The steps now rely on the variable alone. The Mosaic is the same file
  byte for byte.
- The header a client fetches per Mosaic is 177 kB: everything before the
  first tile.
- Lossy WebP is 6% smaller than JPEG at quality 90 on a daytime Rendering and
  39% smaller on a night-time one.
- Scratch space per Slot is 10 GB: the downloads, four lossless renders
  (1.2 to 2.1 GB together) and the lossless Mosaic (2.9 to 3.4 GB). The static
  files are 234 MB.
- A run scheduled for 22:10 on 2026-11-11 and started at 00:45 the next day
  built the 22:00 Slot, not the hour it started in. Looking back for late
  Disks then took 45 s.
- Two renders at once on 16 cores (a Ryzen 9 5950X, all Disks already at
  their sources) built a Slot in 16 min 21 s, against 20 min 18 s for the Slot
  before with one at a time. The four renders took 10 min 35 s together, not
  13 min 20 s, but each alone was slower: 237 to 344 s against 160 to 255 s,
  with 40 to 50 % more CPU time for the same work, which points at memory
  bandwidth, not cores. Two renders held 32.5 GB between them at the peak.
  The join took 153 s on 16 threads against 171 s on 8; the encode did not
  change.
