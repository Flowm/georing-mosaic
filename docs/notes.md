# Notes

What was looked up and measured while building this: the data sources, how
satpy, Prefect and the COG driver behave, and what a Slot costs. The decisions
that rest on these are in [plan.md](plan.md); this file is the evidence.

Facts were looked up on 2026-11-10 to 2026-11-12 from primary sources or live
probes, those on Meteosat-9 and the other satellites considered on
2026-11-14. Terms in capitals are defined in
`GLOSSARY.md`.

## Data sources

| Position | Satellite | Longitude | Source | Download per Slot, day / night | Ready after scan end | Credentials |
|---|---|---|---|---|---|---|
| GOES-East | GOES-19 | 75.2°W | `s3://noaa-goes19/ABI-L1b-RadF/` | 660 / 270 MB | 10–110 s | none |
| GOES-West | GOES-18 | 137°W | `s3://noaa-goes18/ABI-L1b-RadF/` | 662 / 279 MB | 10–110 s | none |
| Himawari | Himawari-9 | 140.7°E | `s3://noaa-himawari9/AHI-L1b-FLDK/` | 652 / 271 MB | 0.5–4.5 min | none |
| Meteosat 0° | MTG-I1 | 0° | EUMETSAT Data Store, `EO:EUM:DAT:0662` and `EO:EUM:DAT:0665` | 1.03 / 0.47 GB and 1.04 / 0.56 GB | about 4.5 min | key and secret |
| Meteosat IODC | Meteosat-9 (MSG-2) | 45.5°E | EUMETSAT Data Store, `EO:EUM:DAT:MSG:HRSEVIRI-IODC` | 0.26 GB, day or night | about 40 s | key and secret |

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

**Meteosat IODC (SEVIRI)**
- One native-format file (`.nat`) per scan holds all twelve channels, so
  there is no per-band download. The product also lists `manifest.xml` and
  `EOPMetadata.xml`, which are not needed.
- Scans start every 15 minutes. The one on the hour senses from 10 seconds
  past to 12 minutes 40 past and is published about 40 seconds later.
- Channels: VIS006, VIS008 and IR_016 by day, IR_039 and IR_108 by night, at
  3 km; HRV at 1 km over part of the disk. There is no blue or green band.
- The spacecraft is in an inclined orbit: on 2026-11-10 at 06:00 it was 7.1°N
  of the equator, at 46.1°E. Level 1.5 data is on the nominal 45.5°E grid.
- The Data Store's other SEVIRI collection, `EO:EUM:DAT:MSG:HRSEVIRI`, is
  Meteosat-10 at 0°, on the same 15-minute cycle.

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
| Meteosat-9 | 13.3 | 14.7 | 0 |

- All four were complete by 15 past in 85% of Slots, by 20 past in 90%, by
  30 past in 93% and by 45 past in 98.5%.
- Meteosat's `updated` times fall in two clusters: about nine Slots in ten near
  14 past, most of the rest near 30 past. The 99th percentile of the joint time
  is 31.5, which is why the deadline is 35 and not 30.
- Whether the later cluster is a first publication or a re-publication of a
  product already downloadable near 14 past is unknown: `updated` keeps only
  the latest value. See "Open items" in the plan.
- Rare long delays exist: two Meteosat Slots many hours late, one Himawari
  Slot at 101 minutes past, one Meteosat-9 Slot at 997 minutes past.
- Meteosat-9 was measured the same way over the same 720 Slots, from the
  search API's `updated` time: complete by 15 past in 99.0% of Slots. It
  does not move the joint figures, which Meteosat at 0° sets.
- Wherever a satellite had no on-the-hour scan, its scan at 10 past existed.

**Licences and attribution**
- GOES: open; NOAA asks for attribution and no implied endorsement.
- Himawari: JMA data distributed by NOAA; both ask for attribution.
- Meteosat: see ADR 0002. Images made from the data are our own; the required
  line is "[Contains modified] EUMETSAT Meteosat data [year]". The policy's
  Article 4 lists "All Level 1 Hourly SEVIRI, FCI and IRS data" as Core data,
  free under CC-BY-4.0 (Article 5); it makes no exception for the Indian Ocean
  service. "Hourly Data" are "those nominal full disk repeat cycles of data
  referenced by EUMETSAT in time to each clock hour (UTC)".

**Where the four satellites leave gaps**

With the 85° limb limit, on a grid of 0.25° between 85°S and 85°N:
- 4.3% of the Earth's area is seen by none of the four, 4.0% of it poleward
  of 60°: no geostationary satellite sees any longitude poleward of 76.5°.
- 14.6% is seen at more than 75° from vertical. At 70°E the steepest view is
  78.5° at the equator, 81.4° at 30°N and 84.7° at 45°N, and nothing sees
  40–110°E north of 45.75°N.
- Any one satellite between 45 and 87°E brings the area seen at more than 75°
  down to about 9.4% and the gap at 40–110°E up to 70–73°N. GK2A at 128.2°E
  brings it to 11.8% and 57.5°N.
- Meteosat-9 takes, by view angle alone, 23–93°E, 19% of the Earth; where it
  sees finer (ADR 0005), 63.5–75°E at the equator and 61.5–76.5°E at 45°N,
  4.1% of the Earth.

**Satellites considered for the India seam**
- Meteosat-9 at 45.5°E: its instrument has no blue or green band and its
  pixels are 3 km. Taken in on 2026-11-14, with its colour looked up from
  MTG-I1's (ADR 0005; "SEVIRI" under "satpy").
- GK2A at 128.2°E (`s3://noaa-gk2a-pds`): open, with real colour bands, but
  too far east to help, 12 to 14 minutes slower, and satpy has no `geo_color`
  for it.
- FY-4B at 105°E: data needs a real-name account with order-based pickup, and
  WMO's registry says its imager failed on 30 July 2026.
- INSAT and Electro-L: no open download found.

**Geostationary data on AWS Open Data** (the registry's 1,501 datasets,
2026-11-14)
- Raw scans: `noaa-goes16` to `noaa-goes19`, `noaa-himawari8` and
  `noaa-himawari9`, and `noaa-gk2a-pds`. Only GOES-18, GOES-19, Himawari-9 and
  GK2A are current: GOES-16 stopped on 2025-04-07, GOES-17 on 2023-01-10 and
  Himawari-8, the backup, last wrote on 2025-11-26.
- GK2A: all sixteen bands, blue and green among them, one NetCDF file per band
  under `AMI/L1B/FD/YYYYMM/DD/HH/`, every 10 minutes. The 02:00 scan of
  2026-11-14 was complete about 30 minutes past.
- `noaa-gmgsi-pds` is NOAA's own hourly global mosaic, in greyscale only
  (visible, two infrared, water vapour), 7.5 MB for the visible. It is the
  only dataset there with Meteosat-9.
- No Meteosat, FY-4, INSAT or Electro-L scans are on AWS.

**Polar orbiters, for the polar caps** (not used)
- VIIRS on NOAA-20 and NOAA-21 is in `noaa-nesdis-n20-pds` and
  `noaa-nesdis-n21-pds`, one file per band per 85-second granule
  (`VIIRS-M3-SDR/`, `VIIRS-I1-SDR/` and so on). On 2026-11-14 granules
  arrived 13 to 57 minutes after sensing, 26 to 30 at the median.
  `noaa-nesdis-snpp-pds` held nothing for that day.
- A pass is not a Slot: using one means imagery from up to about 50 minutes
  either side of the hour.

**City lights (NASA Black Marble, VJ146A4)** (ADR 0006)
- VJ146A4 is NASA's yearly Black Marble from NOAA-20's VIIRS Day/Night Band,
  collection 2 (LAADS archive set 5200): radiance in nW/cm²/sr, corrected
  for moonlight and the atmosphere, at 15″ (240 px per degree). On
  2026-11-15 LAADS held 2018 to 2025; 2025 is 540 tiles of HDF5 named
  `VJ146A4.A2025001.hHHvVV.002.<made>.h5`, 10° × 10° each (h east from
  180°W, v south from 90°N), 51 GB in all, listed without a login at
  `https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/details/allData/5200/VJ146A4/2025/001`.
- Each tile has 28 layers (Black Marble User Guide, collection 2.0, table
  11). The Recipe keeps `AllAngle_Composite_Snow_Free` (float32, fill
  −999.9; below 0.5 set to 0 by NASA) and `Land_Water_Mask` (0 land and
  desert, 1 land, 2 inland water, 3 sea water, 5 coast).
- The download wants an Earthdata Login bearer token. `POST
  https://urs.earthdata.nasa.gov/api/users/find_or_create_token` with the
  user name and password (HTTP Basic) returns the account's token or makes
  one; tokens last 60 days, two per account. Without one LAADS answers 303 to
  its login page. Now and then it answers 502: the build stopped there once
  after 88 tiles, and asks again since.
- Built on 2026-11-15 on a home line: 20 minutes for the 540 tiles at four
  at a time, into a COG of 355 MB (two uint16 bands, ZSTD, overviews to 64).
- NASA data: no licence terms, no attribution required.

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
- There are two official GeoColors. NOAA STAR's GOES-19 full disk
  (`cdn.star.nesdis.noaa.gov/GOES19/ABI/FD/GEOCOLOR/`, JPEG at 10848 px on
  SLIDER's grid kept about ten days, GeoTIFF about three) and GIBS's
  `GOES-East_ABI_GeoColor` (1 km lat/lon, back to 2026-08-10) agree with each
  other within 3 to 11 levels, and with SLIDER by day (STAR 5, GIBS 9 to 13),
  but differ from SLIDER by 31 to 34 at night and 19 to 27 at dawn: NOAA's is
  the older look, with a black night sea and day gone by about 80°. Measured
  on 2026-11-14 on the day, night, dawn and h-dusk scenes. The Recipe follows
  SLIDER; against NOAA it and SLIDER are equally far off (21 to 25 at
  twilight).
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
| day | tuning | GOES-East, 18:00 | Florida, Cuba, the Bahamas | 10, 15, 17 | 4, 6, 5 | 3, 4, 4 |
| night | tuning | GOES-East, 06:00 | the eastern United States | 27, 23, 26 | 25, 22, 23 | 7, 5, 4 |
| terminator | tuning | Meteosat, 18:00 | West Africa and the Atlantic at dusk | 16, 26, 44 | 10, 13, 18 | 7, 8, 11 |
| glint | tuning | GOES-West, 18:00 | the Pacific at 9°S 115°W | 9, 15, 18 | 2, 3, 3 | 1, 2, 1 |
| snow | tuning | Himawari, 06:00 | Mongolia and Lake Baikal | 16, 16, 19 | 8, 10, 13 | 6, 8, 11 |
| dust | tuning | Meteosat, 11:00 | the Sahara around Lake Chad | 15, 13, 18 | 3, 4, 6 | 0, 2, 4 |
| day-ahi | tuning | Himawari, 06:00 | Australia and the Coral Sea | 9, 11, 13 | 3, 5, 5 | 1, 3, 3 |
| day-fci | tuning | Meteosat, 11:00 | the Gulf of Guinea and central Africa | 14, 17, 23 | 3, 5, 5 | 0, 2, 2 |
| night-warm | tuning | Meteosat, 00:00 | the Sahara and the Sahel | 30, 37, 43 | 35, 45, 56 | 2, 1, 1 |
| dawn | tuning | GOES-East, 11:00 | the Caribbean and Venezuela | 11, 19, 25 | 16, 13, 15 | 8, 8, 9 |
| glint-ahi | tuning | Himawari, 02:00 | around New Guinea | 7, 8, 9 | 3, 4, 6 | 2, 2, 4 |
| storms | tuning | Meteosat, 00:00 | thunderstorms over the Congo basin | 35, 29, 39 | – | 1, 1, 1 |
| storms-east | tuning | Meteosat, 18:00 | thunderstorms over Tanzania and Lake Victoria | 23, 20, 24 | – | 3, 2, 2 |
| h-day-ahi | holdout | Himawari, 03:00 | Borneo, Java and Sulawesi | 8, 10, 10 | 3, 7, 8 | 1, 5, 5 |
| h-day-fci | holdout | Meteosat, 12:00 | Iberia, Morocco, the western Mediterranean | 10, 11, 26 | 2, 5, 8 | 0, 3, 6 |
| h-night-cold | holdout | GOES-East, 08:00 | the Pampas at the end of winter | 39, 36, 41 | 36, 37, 40 | 3, 4, 4 |
| h-night-warm | holdout | Meteosat, 01:00 | Libya and Egypt | 22, 27, 31 | 26, 34, 42 | 3, 2, 2 |
| h-dawn | holdout | Himawari, 22:00 | Korea, Japan, the East China Sea | 18, 22, 26 | 17, 20, 23 | 8, 12, 15 |
| h-dusk | holdout | GOES-East, 22:00 | Brazil and Bolivia | 20, 14, 24 | 13, 13, 17 | 5, 5, 7 |
| h-snow | holdout | GOES-East, 15:00 | the Andes at the end of winter | 8, 7, 16 | 3, 9, 4 | 2, 6, 4 |
| h-glint | holdout | Himawari, 22:00 | the central Pacific near 4°N 170°E | 13, 17, 22 | 6, 9, 10 | 4, 7, 8 |
| day-seviri | tuning | Meteosat-9, 06:00 | India before noon | – | – | 27, 23, 14 |
| snow-seviri | tuning | Meteosat-9, 06:00 | the Karakoram, the Himalaya and Tibet | – | – | 28, 22, 17 |
| dusk-seviri | tuning | Meteosat-9, 13:00 | the Arabian Sea and southern India at dusk | – | – | 10, 11, 13 |
| night-seviri | tuning | Meteosat-9, 18:00 | India at midnight | – | – | 17, 21, 25 |
| h-day-seviri | holdout | Meteosat-9, 07:00 (2026-10-01) | Arabia and Oman | – | – | 17, 10, 17 |
| h-night-seviri | holdout | Meteosat-9, 20:00 (2026-10-01) | the Bay of Bengal, Bangladesh, Myanmar | – | – | 4, 4, 4 |

Exact figures are in `difference.json` beside the images. satpy has no
`geo_color` for SEVIRI, and Meteosat-9's scenes were added after the tuning,
so those two columns are empty for them. Its holdout scenes are on
2026-10-01: SLIDER no longer held Meteosat-9 for 14 September on 2026-11-14.
The dust and day-fci scenes are at 11:00 because SLIDER has no Meteosat image
for 12:00 on 2026-11-10. The storm scenes were added during the tuning; before the cloud
layer's ramp was changed, they were 17.5, 18.1, 17.4 and 12.7, 12.9, 12.2,
and before it was fitted to CIRA's storm tops on 2026-11-14 (see the
infrared cloud layer below), 6.2, 6.0, 8.0 and 4.8, 4.8, 4.9.
Until 2026-11-14 our side of each pair had a black frame 3 to 7 px wide:
the Rendering was cropped to the scene's longitudes and latitudes, which fell
3 to 10 km short of SLIDER's rectangle around them. It added 1 to 2 levels
to every figure, and the storm figures above include it. The Recipe column
is measured without it, on 2026-11-14 (the twilight scenes on 2026-11-15
with the twilight compositor, the night scenes, storms, dawn and h-dawn on
2026-11-15 with the new city lights); the `geo_color` and before-tuning
columns are not re-measured and still include it.
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
- **Twilight: the day layer's haze stretched out, the layers mixed as
  light** (`georing.recipe.TwilightCompositor`, replacing satpy's
  day/night compositor). From 76° to 78° of sun zenith the day layer is
  stretched to 1.2, 1.3 and 1.4 times itself less 30, 45 and 65 levels (R,
  G, B), held beyond: that takes out the blue haze the Rayleigh fade leaves,
  the milky veil over dark sea and the blue in cloud shadows. The night layer
  comes in from 82° to 86°, mixed as light (gamma 2.2), where satpy blends
  78° to 88° on display values. Rendered on 2026-11-15: terminator 9.0 to
  8.6, dawn 10.6 to 8.5, dusk-seviri 11.8 to 11.3, holdout h-dawn 13.3 to
  11.1, h-dusk 5.3 unchanged; snow, the only other scene that reaches 76°,
  unchanged. The real renders match the offline model within 0.3. How it
  was found is under "The terminator" below.
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
  layer is level 250, not 255, and its opacity ramps from 296 K down to
  178 K in the tropics and 198 K poleward of 60°, with a gamma of 0.95
  (satpy's ramp ends at 210/230 K). Over storm tops CIRA is brighter the
  colder the top, by about 1.6 levels per kelvin down to 184 K at least, the
  coldest the scenes hold (205 at 200 K, 230 at 184 K), and never flat white.
  A first ramp, linear and opaque at 185 K, was read off the night, night-warm
  and storm scenes; it made every top colder than about 260 K too bright,
  from 5 levels at 236 K to 20 at 184 K, and burned overshooting tops to flat
  white. The level, ramp and gamma were then fitted on 2026-11-14 to CIRA's
  pixels on the two storm scenes, each paired with its 10.4 µm temperature:
  fitted on either scene alone, the other one's cloud (below 280 K) came
  from 5.4 to 3.2 and from 5.0 to 2.2 levels. Rendered, the median per 8 K of
  temperature is now within 3 levels of CIRA's from 184 to 296 K. On the
  warm-ground scenes (night-warm, h-night-warm, both SEVIRI night scenes)
  it costs 0.2 to 0.3, which the fit put on the gamma: a linear ramp
  opaque at 180 K cost them nothing in the fit but left the coldest tops
  about 11 levels too bright. Of the scenes measured, only night reaches
  poleward of 30°, and its coldest top there is 233 K; the 198 K poleward is
  the old 205 K moved by the same 7 K, not measured.
- **The low-cloud layer starts at 0 K over land on every sensor**
  (`georing_low_clouds`). `geo_color` starts it at 1.5 K for FCI. Dry ground
  emits less at 3.9 µm, so CIRA tints it bluish-lilac by night; the Recipe now
  does too, which fixed both warm-ground night scenes.
- **City lights from radiance at 500 m** (ADR 0006, `georing.lights`):
  NASA's Black Marble VJ146A4 for 2025 instead of the Black Marble 2016
  picture at 3 km, warped onto the finest grid instead of the infrared one,
  and coloured by radiance: sea a neutral 8, unlit land (23, 16, 41), lights
  amber from 1.1 nW/cm²/sr to (214, 189, 157) at 140. The colours are the
  median CIRA shows over land of the night and night-warm tuning scenes per
  radiance, under a white infrared veil of the same strength as ours (solved
  per pixel from our render; kept where the three channels agree, so not
  under low cloud), once the veil is taken off. The holdout scenes give the
  same colours, 0 to 10 dimmer from 7 to 30 nW/cm²/sr, and a sea of 7 to 8.
  Carried over from Black Marble 2016 instead (its median brightness at each
  radiance, which saturates at about 30), the lights came out too sparse:
  CIRA lights towns from about 1 nW/cm²/sr. Black Marble 2016's sea was a
  dark grey of 8, not black; made black, the night sea was 7 levels too dark
  in every scene.
  Rendered on 2026-11-15, against the Recipe before: night 6.3 to 5.6,
  storms 3.3 to 0.7, night-warm 1.2, night-seviri 21.7 to 21.1, dawn 8.5 to
  8.3; holdout h-night-cold 4.0 to 3.6, h-night-warm 3.0 to 2.5,
  h-night-seviri 4.0 to 3.5. Worse: storms-east 1.8 to 2.2 and h-dawn 11.1 to
  11.4. Storms gains as Black Marble 2016 kept terrain in its dark land and
  drew the Congo forest near black, where CIRA and now ours show one purple;
  around Lake Victoria CIRA's unlit land is a little lighter than that
  purple.

What still differs from CIRA:
- **The terminator.** With the twilight compositor and the new city lights:
  terminator 8.6, dawn 8.3, dusk-seviri 11.3, holdout h-dawn 11.4 (blue
  worst, 15), h-dusk 5.3.
  What is left: past 84° CIRA's night sea is dark teal with grey low cloud
  where ours is black (ProxyVis, below); Meteosat-12 would take a milder blue
  stretch than GOES and Himawari; ours is short of blue over clear sea at
  66–72° at dusk. Before the compositor, no single setting of the sun-angle limit, the Rayleigh fade or the day/night
  blend (tried: fade strength 0, 0.5, 0.6, fade ending at 84°, blend 76–86,
  80–87, 82–90, 84–92) improves both. GeoColor as published (Miller et al.
  2020, JTECH 37, 429) blends day and night by cos(sun zenith) scaled over
  0.1–0.3 (72.5°–84.3°) and raised to the power 1.5, in display values,
  "bounds selected experimentally based on matching to the observed dimming
  behavior of VIS imagery near the terminator"; that is NOAA's operational
  look. CIRA's 2025 update narrows the twilight zone and extends the day
  side, moving sunrise and sunset by up to an hour (its Quick Guide); the
  formula is not published.
  Studied on 2026-11-14 with the day and night layers rendered apart, on the
  five twilight scenes (offline blends match the rendered Recipe within 0.2):
  at 76–80° the low-sun day layer is up to 20 levels too bright, a milky
  veil over dark sea, and at 80–88° the picture is about 10 too dark, alike
  on ABI, AHI and FCI. Fitted per 2° band, CIRA is close to 0.8 × day from
  78° to 83° with the night layer added on top from about 81° (the weights
  sum to 1.05 to 1.35), and a black-point offset of −13 to −35 levels at dusk
  and −16 to −78 at dawn fits it better still. Weights fitted that way gain
  on the scenes they were fitted to and nothing on the holdout. More
  Rayleigh correction (strength 0 or a fade from 80 to 90°) or the sun-angle
  limit at 76° made every scene worse (terminator 9 to about 20). The sun
  angle at each line's scan time instead of the scan's start also made the
  fits worse. The best candidate, the day layer raised to a power of up to
  1.3 from 74° to 86° and blended in linear light from 82° to 86°, measured
  offline: terminator 9.0 to 8.6, dawn 10.6 to 9.6, dusk-seviri 11.8 to
  11.6, h-dawn 13.3 to 12.3, h-dusk 5.3 unchanged. CIRA's Meteosat-9
  GeoColor ends its day layer near 80°, another scheme.
  Followed up on 2026-11-15 by local contrast (standard deviation of
  brightness in a 15 px Gaussian window) per 2° of sun angle. At 74–80° CIRA
  keeps far more contrast than ours, where ours is still the day layer
  alone: dawn 37/32/31 against 31/23/19, h-dawn 42/47/52 against 37/35/34.
  The veil is in the day layer, not the blend: a contrast-preserving blend
  (Grundland et al. 2006) gains at most 0.1. The day layer with full Rayleigh
  correction matches CIRA's contrast within 3 but is 10 to 40 levels darker.
  Fitted per degree, CIRA ≈ a · day + c with a of 1.1 to 1.3 and c of −7 to
  −46 over 74–80°, a contrast stretch, then the night layer from 82°. A
  smooth form of it, the day layer stretched to 1.2 · day − 35 levels
  (ramped in from 76° to 78°, held beyond) and blended in linear light
  from 82° to 86°, fitted on terminator and dawn only, measured offline:
  terminator 9.0 to 8.9, dawn 10.6 to 8.7, dusk-seviri 11.8 to 11.5, h-dawn
  13.3 to 11.1, h-dusk 5.3 unchanged. It beats the power curve everywhere but the terminator (8.6).
  By eye it is the closest at 78–84°, but cloud shadows stay blue where
  CIRA's are dark and neutral to brown: the haze left in the day layer is
  Rayleigh light, and CIRA takes out more of it in blue. Fitted per channel
  at 78–80°, its offsets are about −40, −60 and −80 (R, G, B) at dawn and
  −40, −85 and −115 on h-dawn, with gains of 1.3, 1.45 and 1.6. A stretch
  per channel of gain 1.3/1.45/1.6 and offset 45/70/100 matches the shadows
  by eye and scores h-dawn 10.1, dawn 9.1, dusk-seviri 11.2, h-dusk 5.4, but
  terminator (Meteosat-12) 11.2; a milder one (1.2/1.25/1.3, 25/37.5/50)
  scores 8.2, 8.9, 11.4, 11.2 and 5.3. The Recipe takes one between them,
  1.2/1.3/1.4 and 30/45/65 (offline 8.6, 8.6, 11.3, 10.8, 5.3). Full Rayleigh correction darkens the
  shadows too but turns the low-sun cloud orange.
  Past 84° CIRA's fine detail stops following our day layer (correlation of
  the image less a 4 px blur: 0.86–0.90 at 84°, 0.3–0.5 at 86°, 0.1 at
  88°), so its day side ends about where ours does; its sea stays dark teal
  instead of black there. Its night detail follows ours at 0.95–0.99 on
  Meteosat-12 but 0.7–0.8 on GOES and 0.4–0.5 on Himawari: CIRA's 2025
  GeoColor draws low cloud over the ocean with ProxyVis (Chirokova et al.
  2023, Wea. Forecasting 38, 2527), a linear regression on infrared bands
  trained on VIIRS Day/Night Band imagery (3.9, 10.3 and 12.3 µm in the
  Quick Guide; the released code's main form adds 8.4 µm), and keeps
  the legacy fog test over land. CIRA's code is on Zenodo (record
  12625308) under the AGPL-3.0; the paper's equations are the part to take.
- **Sun glint on Himawari** (holdout 8.3): ours is 6 to 10 levels darker over
  the glint than CIRA's, and greyer. The AHI glint tuning scene shows no such
  difference.
- **Vegetation on Himawari** is greener and more saturated than CIRA's (New
  Guinea in glint-ahi): the hybrid green, as satpy makes it.
- **Shallow water** is still bluer than CIRA's turquoise, though its mean is
  within 6 levels.
- **City lights are a little softer than CIRA's**, now at 500 m (above); the
  towns and roads are the same. Until 2026-11-15 they were blobs: the Black
  Marble 2016 picture at 3 km, finished on the infrared grid, which cost more
  sharpness than the 3 km source.
- **Snow on Himawari** (tuning 10.7): dry ground is too blue, and high cloud
  is greyer than CIRA's since the cloud-top step was taken out.

**SEVIRI**

satpy reads Meteosat-9 with `seviri_l1b_native` and has no `true_color` or
`geo_color` for SEVIRI. Like FCI's, its grid is stored south first and east
first; the GeoTIFF's pixel width is negative and GDAL warps it right. The
render takes 5 s on eight cores and peaks at 1.5 GB.

The day colour is a table, `src/georing/satpy/seviri_colour.npz`, made with

    georing-fit-colour 2026-11-10T07 2026-11-10T09 2026-11-10T11 \
        2026-09-20T09 2026-09-20T11 --check 2026-11-10T13

For each Slot it puts MTG-I1's day colour before its enhancement (red, the
Recipe's green and blue, Rayleigh-corrected) and SEVIRI's VIS006
(Rayleigh-corrected), VIS008 and IR_016 on one grid of 0.05° over 15°W–60°E,
55°S–55°N, averaging each satellite's pixels into each cell. It keeps cells
both satellites see within 65° of vertical, with the sun within 70° of
overhead, whose 3 by 3 neighbourhood varies by less than 1.5% reflectance or
10% of its own, in both. That leaves 1.9 million cells from the five Slots.
The table has 24 bins per band, in equal steps of the square root of the
reflectance from 0 to 110%; a bin with 10 cells or more holds their median
MTG-I1 colour, the rest a cubic polynomial of the three bands fitted on all
cells. Weighted so that each 2% of SEVIRI's red counts alike, it misses
MTG-I1 by 2.6, 2.6 and 2.6% reflectance (red, green, blue) on the cells it was
made from and by 4.5, 4.3 and 4.1% on 13:00. Clear sea and vegetation are
within 1% at the median; cloud, which the two see from two sides, is within
5%; bright desert is 3% too dark in red.

What was tried on the way:
- **A cubic polynomial alone** misses 13:00 by 4.8, 4.4 and 4.4%, but at the
  median turned dense forest (NDVI over 0.6) teal, blue 5.0 against MTG-I1's
  3.5, and lush crops red: SEVIRI's 8, 31, 17% over central India gave
  8.1, 5.8, 2.4. The table gives 3.9, 4.7, 2.4 for forest and 7.6, 7.2, 4.2
  for those crops, against MTG-I1's 6.7, 8.2, 5.5 where it sees the like.
- **The November Slots alone** hold only 43 cells near those crops; the
  September Slots, with the Sahel green after the rains, were added for them.
- **Weighting by SEVIRI's red alone** puts dark sea and dense forest, which
  share a red, in one class, and sea is far more common; a polynomial then
  bends toward the sea. Weighting by red and 0.8 µm together helped forest
  but not sea; the table needs neither.
- **An evenness limit of 1.5% alone**, without the 10% share, kept almost no
  cloud: MTG-I1's blue then never rose above about 20%.

Against Himawari's real colour over north India at 06:00 on 2026-11-10 (both
Renderings warped to 0.02°), Meteosat-9's forest and crops are green and
olive, Himawari's greener and much hazier: it sees the plain at about 66°.
CIRA's Meteosat-9 GeoColor paints the sea grey and the land a vivid green,
neither as MTG-I1 shows them; that is most of the difference in the table
above.

By night, SEVIRI's 10.8 − 3.9 µm difference runs higher than FCI's
10.5 − 3.8 µm over the same ground at the same time. Medians on the same
grid at 2026-11-10 00:00, where FCI's 10.5 µm reads 285–295 K: 2.6 K over
land and 3.3 K over sea (2.4 and 2.9 K at 270–285 K). With the low-cloud ramp
starting at 0 K as for the others, clear ground came out as a pale-blue
sheet (night-seviri 58, 87, 109). The ramp for SEVIRI starts at 2.6 K over
land and 3.3 K over sea. Its 10.8 µm reads 0.15 K above FCI's 10.5 µm, which
the high-cloud layer can ignore.

**Static files, fetched at image build**
- `gshhs_land_water_mask_3km_i.tif`, 0.5 MB, from
  `https://zenodo.org/records/10076199/files/`, into
  `<data_dir>/composites/`, with `SATPY_DOWNLOAD_AUX=False`. Its URL and
  checksum are in `georing.static` only.
- `georing-static` fetches it, and pyspectral's Rayleigh tables (54 MB)
  and spectral responses (5 MB), and points pyspectral at them offline.
- The city lights are not among them: the flow builds them once under the
  work directory (`georing.lights`; above, under "Data sources"). Until
  2026-11-15 they were `BlackMarble_2016_3km_geo.tif`, which satpy 0.60.0
  could not download (NASA had moved it).
- **Warping the lights onto a satellite's grid.** A warped VRT copied to a
  GeoTIFF fails on Meteosat's grid with "Unknown GDAL Error": the grid
  reaches past the Earth's edge (±5,568 km, the Earth ends near 5,434), so
  whole chunks have no source and GDAL gives up ("Cannot determine source
  window"), `ERROR_OUT_IF_EMPTY_SOURCE_WINDOW=NO` and `SAMPLE_GRID=YES`
  notwithstanding. GOES's grid ends at the Earth's edge and warps. FCI's
  grid also runs south-up (its extent has north and south swapped), which
  GDAL does not warp onto. `georing.lights.layer` warps strips of 512 rows
  with `rasterio.warp.reproject`, upright, skips a strip whose sampled points
  all miss the Earth, and flips each strip into place: 21 s for Meteosat's
  0.5 km grid, once per grid.

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
- **The city lights at 0.5 km** (2026-11-15, the 18:00 Disks of 2026-11-10,
  eight cores, the warp of the lights already kept): with the clouds and the
  lights put together on the finest grid as three layers, GOES-East took 164
  s and 22.0 GB and Meteosat 201 s and 28.9 GB, against 104 s and 11.7 GB and
  170 s and 22.5 GB for the Recipe before, measured the same day. The upsampled
  layers' chunks are 16 times their infrared size, three layers came up
  where one did, and the lights came as float64; float32 and chunks matched
  to the clouds' still left 19.2 and 26.4 GB. With the clouds put together
  on the infrared grid first and only that layer and the lights joined at
  0.5 km: GOES-East 141 s and 12.2 GB, Meteosat 178 s and 21.0 GB, the same
  picture to the decimal. Read in the finest band's chunks instead of the
  clouds', the lights cost 2.3 GB more on GOES-East (14.5) and 0.7 more on
  Meteosat (21.7), the same picture again. Warping the lights onto a grid takes 20 to 30 s,
  once per satellite.
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
- For a satellite whose pixels are coarser it compares not the view angle
  but the angle at which a 1 km imager would see as finely,
  arccos(cos(angle) / km). For Meteosat-9's 3 km that is 70.5° straight
  below it. That angle changes about a seventh as fast across the ground as a
  view angle, so a 5° feather would be 900 to 1,300 km wide. At 2.5° it is
  440 to 690 km between the equator and 60°N, the Seam between the two GOES
  485 to 940 km.
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
- With Meteosat-9, the 06:00 Slot of 2026-11-10, built from a shell on
  2026-11-14 with two renders at once on 16 cores, took 11 min 40 s with all
  five Disks: Meteosat-9's download 260 MB and 43 s, its render under 10 s;
  the join 2 min 35 s. Its Mosaic is 309 MB. Seen at full resolution, the
  strip Meteosat-9 shows is softer than its neighbours, being 3 km, and
  clouds in its Seams look smeared rather than doubled.
- Two renders at once on 16 cores (a Ryzen 9 5950X, all Disks already at
  their sources) built a Slot in 16 min 21 s, against 20 min 18 s for the Slot
  before with one at a time. The four renders took 10 min 35 s together, not
  13 min 20 s, but each alone was slower: 237 to 344 s against 160 to 255 s,
  with 40 to 50 % more CPU time for the same work, which points at memory
  bandwidth, not cores. Two renders held 32.5 GB between them at the peak.
  The join took 153 s on 16 threads against 171 s on 8; the encode did not
  change.
