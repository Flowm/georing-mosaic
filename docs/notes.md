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
  of the equator, at 46.1°E; on 2026-11-15 at 18:00 6.5°S, at 46.1°E. Level
  1.5 data is on the nominal 45.5°E grid, as if seen from the equator, so
  the rim of that grid away from the satellite is not scanned: at 18:00 on
  2026-11-15, 0.9% of the nominal disk's pixels, a ring at the limb from
  81°S to 81°N, missing in every band. The Rendering fills them with the
  static night ground and lights, and the Mosaic keeps them up to its 85°
  limit, which it works out from the nominal position: over Siberia a dark
  lens with lights in it, and beside it a strip seen at more than 85° whose
  infrared reads cold and white. The orbital parameters satpy gives
  (`satellite_actual_latitude` and so on) hold the true position. Since
  2026-11-15 the render step writes it into the Rendering's tags and the
  join takes the larger of two view angles: from where the satellite was,
  and from its grid's nominal position. The first drops the unscanned rim
  and what was seen past 85° on the far side (over Siberia at 18:00, 1.1% of
  the world's pixels; Himawari takes over to the east); the second keeps the
  near side to what the grid holds. With the true position alone, the join
  took ground 6.5° further south that the satellite saw but its grid does
  not hold, and warping it drew orange, teal and grey shards off
  Antarctica. Taken from the scene, the position was lost: the night
  layer's static images carry no orbit, satpy's merged metadata drops it,
  and for Meteosat-9, all on one 3 km grid, the bands are unloaded before
  the render step looks; `TwilightCompositor` hands it on from the day layer.
  ABI's files give no actual position (the GOES stay on the equator, under
  0.1° off); AHI's is 0.02°S, FCI's 0.66°S.
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
- Himawari: JMA data distributed by NOAA; both ask for attribution. The
  Item names them "JMA, via NOAA", with NOAA's disclaimer once for all the
  satellites it distributes.
- Meteosat: see ADR 0002. Images made from the data are our own; the required
  line is "[Contains modified] EUMETSAT Meteosat data [year]". The policy's
  Article 4 lists "All Level 1 Hourly SEVIRI, FCI and IRS data" as Core data,
  free under CC-BY-4.0 (Article 5); it makes no exception for the Indian Ocean
  service. "Hourly Data" are "those nominal full disk repeat cycles of data
  referenced by EUMETSAT in time to each clock hour (UTC)".

**Where the four satellites leave gaps** (before Meteosat-9)

With the 85° limb limit, on a grid of 0.25° between 85°S and 85°N:
- 4.3% of the Earth's area is seen by none of the four, 4.0% of it poleward
  of 60°: no geostationary satellite sees any longitude poleward of 76.5°.
- 14.6% is seen at more than 75° from vertical. At 70°E the steepest view is
  78.5° at the equator, 81.4° at 30°N and 84.7° at 45°N, and nothing sees
  40–110°E north of 45.75°N.
- Any one satellite between 45 and 87°E brings the area seen at more than 75°
  down to about 9.4% and the gap at 40–110°E up to 70–73°N. GK2A at 128.2°E
  brings it to 11.8% and 57.5°N.
- Meteosat-9 takes, by view angle alone, 23–93°E, 19% of the Earth (ADR
  0005, since 2026-11-18); where it sees finer (before), 63.5–75°E
  at the equator and 61.5–76.5°E at 45°N, 4.1% of the Earth.

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
  after 88 tiles. It also answers 404 for a tile it lists and serves a
  minute later: the first build in the compose stack (2026-11-15, the 18:00
  Slot) stopped so after 76 tiles, and with it that Slot. Every answer but a
  refused login (401, 403) is now asked again, four times, 10 to 80 s
  apart.
- Built on 2026-11-15 on a home line: 20 minutes for the 540 tiles at four
  at a time, into a COG of 355 MB (two uint16 bands, ZSTD, overviews to 64).
- NASA data: no licence terms, no attribution required.
- No tile lies south of 70°S (v16 and v17 are missing from the list), so
  the COG holds Antarctica beyond 70°S as sea: in the 16:00 Slot of
  2026-11-16 the night layer under Himawari's southern limb turned from
  unlit land (lilac) to sea (grey) along exactly 70°S. The land band there
  reads 100 at 69.9°S and 0 from 70.1°S. As the lights are warped onto a
  satellite's grid, the share of land south of 70°S now comes from the
  GSHHS mask; Himawari's view of the Ross Sea at that hour shows the
  Antarctic ice as unlit land across 70°S, as CIRA's does.

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
  to lat/lon; SLIDER carries it for all five satellites, unregridded.
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
  warps the land mask onto the satellite's coarsest band grid, where the
  cloud layers are made, and the city lights onto its finest, where the night
  layer is finished after the last resample (ADR 0006). The warped lights are
  kept under `<work_dir>/grids/`; the land mask takes about 3 s and is warped
  for every render. The night layer's clouds are therefore 2 km data for GOES
  and Himawari, 1 km for MTG-I1 and 3 km for Meteosat-9, as the infrared
  bands are.
- satpy's background compositor fills the clouds everywhere, so where a
  satellite scanned no infrared the night layer was the city lights alone,
  opaque. Meteosat-9's scans miss rows at both ends of its grid: on
  2026-11-19 it holds data in rows 52–3639 of 3712 at 21:00, 75–3658 at
  03:00 and 57–3658 at 00:00. At 21:00 its infrared ends at 72.7°N, where
  its 85° limit lies near 76.5°N, and from 15:00 on every evening Slot was
  flat black, (8, 8, 8) at full opacity, over 20–70°E north of about 73°N.
  The night layer is now missing where the 10.4 µm band is: in the 21:00
  Rendering 65,000 pixels turned transparent, rows 3640–3659 and the rest
  of the rim, north and south, all seen beyond 81° (median 86°). Only MTG-I1
  sees part of it within 85°, west of about 35°E and south of 74°N; the rest
  joins the polar gap.
- [Issue #3397](https://github.com/pytroll/satpy/issues/3397) proposes a
  different sun-angle correction for the built-in composites, so the look may
  change between releases.

**Recipe**

The Comparison scenes come in two sets. The **tuning set** (2026-11-10, and
four scenes from 15 to 19 November for a low sun and the limbs) is what
curves are read off and what changes are looked at. The **holdout set**
(2026-09-14, the oldest day SLIDER still held for the four satellites of
then on 2026-11-11, and 2026-11-14 and 2026-10-01; at places no tuning scene
covers) is only measured: no parameter
is fitted to it or adjusted against it by eye. `georing-compare --set
holdout` runs it alone. The figures are the mean absolute difference from
CIRA's GeoColor per channel (red, green, blue), in levels of 255, for
satpy's `geo_color`, for the Recipe before it was tuned and for the Recipe
now.

| Scene | Set | Satellite, UTC | Place | `geo_color` | Before tuning | Recipe |
|---|---|---|---|---|---|---|
| day | tuning | GOES-East, 18:00 | Florida, Cuba, the Bahamas | 10, 15, 17 | 4, 6, 5 | 3, 4, 4 |
| night | tuning | GOES-East, 06:00 | the eastern United States | 27, 23, 26 | 25, 22, 23 | 7, 5, 4 |
| terminator | tuning | Meteosat, 18:00 | West Africa and the Atlantic at dusk | 16, 26, 44 | 10, 13, 18 | 6, 8, 11 |
| glint | tuning | GOES-West, 18:00 | the Pacific at 9°S 115°W | 9, 15, 18 | 2, 3, 3 | 1, 2, 1 |
| snow | tuning | Himawari, 06:00 | Mongolia and Lake Baikal | 16, 16, 19 | 8, 10, 13 | 5, 8, 11 |
| dust | tuning | Meteosat, 11:00 | the Sahara around Lake Chad | 15, 13, 18 | 3, 4, 6 | 0, 2, 4 |
| day-ahi | tuning | Himawari, 06:00 | Australia and the Coral Sea | 9, 11, 13 | 3, 5, 5 | 1, 3, 3 |
| day-fci | tuning | Meteosat, 11:00 | the Gulf of Guinea and central Africa | 14, 17, 23 | 3, 5, 5 | 0, 2, 2 |
| night-warm | tuning | Meteosat, 00:00 | the Sahara and the Sahel | 30, 37, 43 | 35, 45, 56 | 2, 1, 1 |
| dawn | tuning | GOES-East, 11:00 | the Caribbean and Venezuela | 11, 19, 25 | 16, 13, 15 | 8, 9, 10 |
| glint-ahi | tuning | Himawari, 02:00 | around New Guinea | 7, 8, 9 | 3, 4, 6 | 2, 2, 4 |
| storms | tuning | Meteosat, 00:00 | thunderstorms over the Congo basin | 35, 29, 39 | – | 1, 1, 1 |
| storms-east | tuning | Meteosat, 18:00 | thunderstorms over Tanzania and Lake Victoria | 23, 20, 24 | – | 3, 2, 2 |
| h-day-ahi | holdout | Himawari, 03:00 | Borneo, Java and Sulawesi | 8, 10, 10 | 3, 7, 8 | 1, 5, 5 (reference lost) |
| h-day-fci | holdout | Meteosat, 12:00 | Iberia, Morocco, the western Mediterranean | 10, 11, 26 | 2, 5, 8 | 0, 3, 6 (reference lost) |
| h-night-cold | holdout | GOES-East, 08:00 | the Pampas at the end of winter | 39, 36, 41 | 36, 37, 40 | 3, 4, 4 |
| h-night-warm | holdout | Meteosat, 01:00 | Libya and Egypt | 22, 27, 31 | 26, 34, 42 | 3, 2, 2 (reference lost) |
| h-dawn | holdout | Himawari, 22:00 | Korea, Japan, the East China Sea | 18, 22, 26 | 17, 20, 23 | 8, 12, 15 (reference lost) |
| h-dusk | holdout | GOES-East, 22:00 | Brazil and Bolivia | 20, 14, 24 | 13, 13, 17 | 4, 4, 4 |
| h-snow | holdout | GOES-East, 15:00 | the Andes at the end of winter | 8, 7, 16 | 3, 9, 4 | 2, 6, 4 |
| h-glint | holdout | Himawari, 22:00 | the central Pacific near 4°N 170°E | 13, 17, 22 | 6, 9, 10 | 4, 7, 8 (reference lost) |
| day-seviri | tuning | Meteosat-9, 06:00 | India before noon | – | – | 27, 23, 14 |
| snow-seviri | tuning | Meteosat-9, 06:00 | the Karakoram, the Himalaya and Tibet | – | – | 28, 22, 17 |
| dusk-seviri | tuning | Meteosat-9, 13:00 | the Arabian Sea and southern India at dusk | – | – | 10, 11, 13 |
| night-seviri | tuning | Meteosat-9, 18:00 | India at midnight | – | – | 17, 21, 25 |
| h-day-seviri | holdout | Meteosat-9, 07:00 (2026-10-01) | Arabia and Oman | – | – | 17, 10, 17 |
| h-night-seviri | holdout | Meteosat-9, 20:00 (2026-10-01) | the Bay of Bengal, Bangladesh, Myanmar | – | – | 4, 4, 4 |
| glint-seviri | tuning | Meteosat-9, 03:00 (2026-11-19) | the sun's reflection south of India | – | – | 33, 28, 25 |
| limb-south-dawn | tuning | Meteosat, 03:00 (2026-11-19) | sea ice and cloud on MTG-I1's southern limb at dawn | – | – | 15, 15, 15 |
| lowsun | tuning | GOES-West, 19:00 (2026-11-15) | the North Pacific under a low midday sun | – | – | 7, 9, 10 |
| limb-dawn | tuning | Meteosat, 02:00 (2026-11-16) | the Indian Ocean on MTG-I1's eastern limb at dawn | – | – | 21, 21, 20 |
| h-limb-dusk | holdout | Meteosat, 21:00 (2026-11-14) | MTG-I1's western limb at dusk over Brazil and the South Atlantic | – | – | 10, 10, 10 |
| h-lowsun | holdout | Meteosat, 13:00 (2026-11-14) | the North Atlantic under a low midday sun | – | – | 8, 12, 17 |

The five scenes whose reference was lost were dropped from `georing-compare`
on 2026-11-18; their rows keep the figures last measured. Exact figures are
in `difference.json` beside the images. satpy has no
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
2026-11-15 with the new city lights, the low-sun scenes, snow and the
twilight scenes again on 2026-11-15 with the wider stretch); the `geo_color`
and before-tuning columns are not re-measured and still include it.
The low-sun scenes were added on 2026-11-15, after the twilight stretch
whitened cloud where the sun stays at 74–86° around midday, which the
twilight scenes (mostly dark sea at dusk) had not shown.
On 2026-11-15 the local `work/` directory was deleted. The references of
h-day-ahi, h-dawn and h-glint (Himawari) and of h-day-fci and h-night-warm
(Meteosat) are lost with it: SLIDER no longer held 2026-09-14 for those two
satellites. Their figures stand as last measured and can no longer be
measured again. Every other reference was still on SLIDER that day.
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
  day/night compositor). From 72° to 82° of sun zenith, on a smooth step,
  the day layer is stretched to 1.16, 1.24 and 1.32 times itself less 24, 36
  and 52 levels (R, G, B), held beyond: that takes out the blue haze the
  Rayleigh fade leaves, the milky veil over dark sea and the blue in cloud
  shadows. The night layer comes in from 82° to 86°, mixed as light (gamma
  2.2), where satpy blends 78° to 88° on display values.
  First built on 2026-11-15 at full strength (1.2/1.3/1.4 less 30/45/65)
  over 76–78°: terminator 9.0 to 8.6, dawn 10.6 to 8.5, dusk-seviri 11.8 to
  11.3, holdout h-dawn 13.3 to 11.1. In the first Mosaics it pushed bright
  cloud past white, blue first, and drew an edge across cloud fields where
  the November sun stays at 74–86° around midday (the North Pacific, the
  Southern Ocean). Over bright cloud on lowsun it rose from 192 to 210
  between 75° and 78° where CIRA rises from 197 to 204, then stayed 20 below
  CIRA at 83–85°. A black point that keeps white white (tried at 0.06–0.14,
  0.1–0.18, 0.14–0.26) took the edge out but left low-sun cloud 10 darker
  than CIRA, which does whiten it; highlights rolled softly into white, and a
  later blend (83–87, 84–88), did not help. The wider, milder, smooth ramp,
  rendered on 2026-11-15: terminator 8.4 to 8.2, dawn 8.3 to 8.8,
  dusk-seviri 11.2 to 11.3, lowsun 9.1 to 8.7, snow 8.0 to 7.9; holdout h-dusk
  3.7 to 3.6, h-lowsun 13.1 to 12.4. Over bright cloud its gap to CIRA on
  lowsun fell from 8.4 to 6.7, and no edge shows. How the stretch was found
  is under "The terminator" below.
- **Glare on a limb at twilight gives way to the night layer**
  (`glare_sun`, `glare_angle` on `georing`). Where a satellite looks into a
  low sun's reflection over the sea, the day layer burnt out to white: the
  02:00 Slot on 2026-11-16 showed a white stripe from MTG-I1's eastern limb
  down to the Southern Ocean, cut off where Meteosat-9 takes over at 62°E.
  There MTG-I1 sees the sea 70–78° off vertical under a sun of 72–84°, and its
  raw red reads 58–107% where Meteosat-9, seeing the same sea at 33°, reads
  3.5–4%: 10 to 25 times as bright, with the glint angle (between the view
  and the sun's mirror image) under 30°. Divided by the sun it reached 250 to
  450%, and satpy's Rayleigh correction, which takes a red band above 20% for
  cloud and is relaxed to nothing at 100%, left it all in. pyspectral's
  Rayleigh table puts only 15–27% of red there; the rest is the sea's
  reflection and forward scatter, nothing of the ground. So the day layer's
  share falls, times the water fraction of the land mask, as the sun goes
  from 65° to 72° and the glint angle from 40° to 20°. Burnt-out pixels on
  limb-dawn went from 10% to 0.02%. Over land the same fade swapped daylit
  cloud over Bolivia for the night layer at MTG-I1's western limb on
  2026-11-15 21:00, where CIRA and ours showed cloud by day, hence the water
  only. The sea beyond the coast still goes to night, a hard step at the
  coastline off Argentina on h-limb-dusk (2026-11-14 21:00); the Mosaic
  takes GOES-East there. Against CIRA, which burns its limbs out as ours
  did, limb-dawn went from 5.8, 5.8, 5.9 to 25.2, 25.1, 24.5 and h-limb-dusk
  from 6.3, 6.8, 7.1 to 11.9, 12.4, 12.6 (burnt-out pixels 10.7% to 8.3%,
  CIRA's 11.8%). The other 16
  scenes rendered with it on and off (every one with a low sun or glint) are
  the same to the pixel. A rim of white stays at the very edge, beyond 80° of
  view and under a sun higher than 65°; the Mosaic takes another satellite
  there. The 02:00 Slot built again with it: the stripe is grey cloud and
  dark sea, burnt-out pixels between 15°E and 100°E fell from 8.9% to 1.6%
  (most of the rest Antarctic ice, which is land and white), and the largest
  render peaked at 22.8 GB, the Slot taking 26 minutes.
  Since 2026-11-19 it acts only as far as the day layer is burnt out, as
  its brightest band goes from 0.88 to 0.98 (`burnt`). Meteosat-9's day
  layer, whose low-sun grey is capped, is not: where the fade acted at 00:00
  on 2026-11-19 its median was 0.80 (MTG-I1's on limb-dawn 0.96), and the
  fade swapped it for the night layer's black sea at about 0.22, a dark band
  along its limb that the map showed as straight north–south stripes over
  the dawn, cut off at the Himawari Seam. With the gate the stripes are gone.
  limb-dawn went from 25.2, 25.1, 24.5 to 20.8, 20.7, 20.1, h-limb-dusk from
  11.9, 12.4, 12.6 to 9.5, 9.9, 10.1, with burnt-out pixels unchanged (0.25%
  to 0.26%, 13.41%); terminator, dawn, dusk-seviri and h-dusk are unchanged.
  The white glow on MTG-I1's southern limb at 03:00 on 2026-11-19 (0–40°E,
  52–72°S) is not glare: the glint angle there is about 40°, under a sun
  81–82° from the zenith and a view of 69–79°, sunlit ice and cloud seen
  slantwise. CIRA's GeoColor draws it the same (limb-south-dawn): means
  155.8, 159.8, 161.8 against CIRA's 156.6, 159.7, 162.1, burnt-out pixels
  21.4% against 20.0%. It is left as it is.
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
- **The low-cloud layer starts at 0 K over land on every sensor but SEVIRI**
  (`georing_low_clouds`), whose starts at 2.6 K over land and 3.3 K over sea
  (`seviri.yaml` says why). `geo_color` starts it at 1.5 K for FCI. Dry ground
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
- **City lights come on as the sun sets** (2026-11-22). They came in with the
  night layer, 82–86°, and were at full strength from 86°, the sun still 4°
  above the horizon, across a strip some 450 km wide: in the Mosaics of
  2026-11-21 17:00 and 23:00 and 2026-11-22 11:00 to 13:00 the median of lit
  land (over 20 nW/cm²/sr) rose from that of unlit land at 82° to 50–80
  levels above it at 84–86° and stayed there. CIRA's Meteosat-9 GeoColor
  does the same (2026-11-22 02:00: off to 85°, full from 86°). The Recipe
  now dims the lights' radiance by up to three powers of ten, lifted on a
  smooth step as the sun goes from 80° to 90° (`dusk` and `decades` of
  `georing_city_lights`): half-way at 85°, full by sunset (90.8° with
  refraction); the bright cores come on first. The sun zenith is worked out
  on the infrared grid and stands for the 0.5 km pixels under it. Compared
  on Meteosat-9's 01–03 and 11–13 UTC Disks of 2026-11-22, with the fade
  from 78–88°, 80–90°, 80–92°, 82–94°, 84–96°, 86–98° and 88–98°; the
  owner chose 80–90°. Lit land above unlit, against about 85 at full: at 86°
  under 78–88° 60–80 at dawn and 25–60 at dusk, close to no fade; under
  80–90° 15–40 at dawn and full by 90°; under 84–96° about 0 at 86° and 0–25
  at sunset, a dark band between the day and the lit cities. Against CIRA,
  which switches hard, only terminator moved, 6.1 to 6.0 in red (84–96° also
  moved dawn, 8.5 to 8.6 in green), and h-dusk not at all: lit pixels are
  few. The other scenes are unchanged, the tint fade over water only
  included (no scene has Meteosat-9's land under a sun of 64–76°).

What still differs from CIRA:
- **The terminator.** With the twilight compositor, its wider stretch and the
  new city lights: terminator 8.2, dawn 8.8, dusk-seviri 11.3, lowsun 8.7;
  holdout h-dusk 3.6, h-lowsun 12.4 (blue worst, 17: CIRA's low-sun cloud
  is bluer than ours).
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

    georing-fit-colour \
        --meteosat-0 2026-11-10T07 2026-11-10T09 2026-11-10T11 2026-09-20T09 2026-09-20T11 \
        --himawari 2026-11-10T03 2026-11-10T05 2026-11-10T07 2026-11-10T09 2026-09-20T05 2026-09-20T09 \
        --check 2026-11-10T13 2026-11-19T05

(Until 2026-11-19 it was made from MTG-I1 alone, on the five MTG-I1 Slots;
the figures in this paragraph are that table's. Himawari's land was added
then; see below.)

For each Slot it puts MTG-I1's day colour before its enhancement (red, the
Recipe's green and blue, Rayleigh-corrected) and SEVIRI's VIS006
(Rayleigh-corrected), VIS008 and IR_016 on one grid of 0.05° over 15°W–60°E,
55°S–55°N, averaging each satellite's pixels into each cell. It keeps cells
both satellites see within 65° of vertical, with the sun within 70° of
overhead, whose 3 by 3 neighbourhood varies by less than 1.5% reflectance or
10% of its own, in both. That leaves 1.9 million cells from the five Slots.
Since 2026-11-22 the view angles are those the join counts, from where each
satellite was: on 2026-09-20 at 09:00 Meteosat-9 stood at 7.6°N, and 9% fewer
of its cells over MTG-I1's overlap are within 65° than with it on the
equator. The table in use was made before that and has not been made again.
The cells of each Slot are kept under `work/comparison/fit`, named by the
settings that picked them, so that a change to those picks them again.
The table has 24 bins per band, in equal steps of the square root of the
reflectance from 0 to 110%; a bin with 10 cells or more holds their median
MTG-I1 colour, the rest a cubic polynomial of the three bands fitted on all
cells. Weighted so that each 2% of SEVIRI's red counts alike, it misses
MTG-I1 by 2.6, 2.6 and 2.6% reflectance (red, green, blue) on the cells it was
made from and by 4.5, 4.3 and 4.1% on 13:00. Clear sea and vegetation are
within 1% at the median; cloud, which the two see from two sides, is within
5%; bright desert is 3% too dark in red.

Learnt from MTG-I1 alone, over Africa, Arabia and Europe, the table made
India olive-brown and the hazy Arabian Sea salmon, where Himawari shows
green crops under a blue-grey haze (2026-11-19 03:00, both Renderings side
by side). SEVIRI's bands for India's crops are those of Africa's savanna,
and MTG-I1's pixels outnumber anything else 80 to 1, so its colour decided
every such bin. Since 2026-11-19 the table also learns from Himawari, where
it and Meteosat-9 both see the ground within 65° (70–125°E): its clear land
only (the land mask, and SEVIRI's brightest band under 40%), on six Slots,
two of them morning ones, as India is seen at 03:00. What was tried on the
way, by mean |difference| on the cells (red, green, blue):

- **Both satellites, sea and land, on eight Slots each**: Himawari's cells
  9.7, 9.4, 9.5 to 5.9, 6.0, 6.5, MTG-I1's 3.1 to 3.2; but day-seviri's sea
  (2026-11-10 06:00) turned a pale, blotchy grey with hard-edged patches.
  Himawari sees that sea 50–65° off vertical, through more haze.
- **Himawari's land only, on the same eight**: the sea stayed blotchy. The
  cause was MTG-I1's morning Slots (05:00), its view low and slantwise over
  the western Indian Ocean.
- **Both on MTG-I1's five Slots**: the sea clean, but India hardly greener:
  only 23,000 of Himawari's cells.
- **Each neighbour's median averaged where both have cells**: vegetation's
  green 6.4 to 6.6 only.
- **Himawari's land with its cloud**: bright cloud (SEVIRI 85, 85, 40%)
  turned blue, 77.8, 82.5, 86.3 against 80.0, 83.3, 83.3: Himawari sees it
  slantwise too.

The table now: MTG-I1 on its five Slots and Himawari's clear land on six,
1.92 million cells, 2.7, 2.6, 2.6% on them. On 2026-11-10 13:00 it misses
MTG-I1 by 4.5, 4.3, 4.1, as before; on 2026-11-19 05:00 Himawari's clear
land by 2.6, 2.3, 2.5. Vegetation on Himawari's land that hour, at the
median: 5.3, 7.7, 4.4, against 5.6, 6.4, 4.1 before and Himawari's 4.5,
8.2, 4.5; bright cloud 80.0, 83.5, 83.5. India at 03:00 is green under a
blue-grey haze. Against CIRA: day-seviri 27.1, 22.7, 14.2 to 26.5, 21.3,
14.5, snow-seviri 28.0, 21.5, 17.2 to 28.2, 21.9, 17.6; dusk-seviri,
glint-seviri and h-day-seviri within 0.1. The salmon tint of the hazy
Arabian Sea at 03:00 stays, as the sea is learnt from MTG-I1 only, and so
do the orange specks along cloud at Meteosat-9's dawn (0.73% to 0.72% of
the pixels at 00:00).

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

Outside what the table was learnt on, it is not to be trusted. At the
southern limb on 2026-11-15 at 23:00 (the satellite 5.3°N), 55–72°S under a
sun 75–87° from the zenith, the bands divided by the sun angle reached a
median of 150, 214 and 190% (VIS006, VIS008, IR_016), up to 340%, where the
table ends at 110% and is held at its edge; its brightest corners, filled by
the polynomial, gave about 37, 15, 0: a large orange patch over Antarctica
in the Mosaic, a thin strip in the evening Slots. Since 2026-11-15 the
colour fades, over 10°, to a neutral grey as bright as VIS008 beyond a view
of 65° (the table's limit) or a sun of 80°. Orange pixels there: 3,358 to
none. A sun fade from 70° (the table's limit too) greyed dusk-seviri from
9.8, 11.0, 13.2 to 11.2, 12.6, 14.3; from 80° it is 9.6, 11.0, 13.0.
day-seviri, snow-seviri and h-day-seviri are unchanged either way.

The 01:00 Slot on 2026-11-16 still showed an orange
spot at 67–70°E, 40–48°S and salmon streaks around it, under a sun of 73–81°
and a view of 61–72°: the corrected bands there reach about 103, 128 and
106%, past the table's end, while the fade from 65° had barely begun. The
grey had its own fault: VIS008 divided by a sun near 80° turned the limb
white, about 170 against CIRA's 105–110. On that limb (52–78°E, 38–62°S,
against CIRA's Meteosat-9 GeoColor) the colour now also fades as the
brightest band goes from 110 to 130%, the view fade runs from 58° to 66° (the
sun's, sharing its width, from 80° to 88°), and
the grey is the uncorrected VIS008 divided by the sun taken no lower than
60°. Orange pixels in the comparison image went from 5,338 to none, and the mean
|difference| from 68.7, 62.9, 65.6 to 52.4, 48.9, 53.9. Swept on the full
disk, the view fade from 65° left 14,258 pink pixels on that limb, from 60°
4,397, from 58° 186; the reach fade alone left the streaks. Capping the
grey's sun at 70° gave 64.4, 59.9, 63.3, at 60° 54.7, 50.0, 53.4, and no
correction at all 36.2, 31.2, 35.0, with 433 orange pixels where the view
fade alone greys. Ours is still brighter there than CIRA's, a mean of about
155 against 105–110, and white where CIRA's limb is a muted olive grey.
day-seviri, snow-seviri, dusk-seviri and h-day-seviri are unchanged
(dusk-seviri 9.7, 10.9, 12.4).

The table never saw the sun's reflection on the sea, and gave it a desert's
colour: on 2026-11-19 at 03:00 a beige disk about 15° across south of India
(85°E, 10°S), orange at its centre, cut off at the Himawari Seam. On open
sea there (62–92°E, 30°S–5°N), the median colour by glint angle runs about
80, 85, 95 within 20°, blue less red 6 to 21, against 13, 44, 72 from 24°
out, blue less red about 55. Over water the colour now fades to the grey
from a glint angle of 22° to 12°, over the land mask (0 water, 100 land):
a grey sheen where the disk was, as Himawari and the GOES draw glint and
as CIRA's Meteosat-9 GeoColor does. A fade from 25° to 15° spread the
sheen past the disk. The glint-seviri scene (that hour, 72–98°E, 22°S–2°N)
went from 38.8, 28.7, 18.9 to 33.4, 28.1, 24.9: CIRA paints all of
Meteosat-9's sea grey, so the figure moves little either way, and the
images are the measure. day-seviri, snow-seviri, dusk-seviri and
h-day-seviri are unchanged.

The table was made under a sun within 70° of overhead. Under a lower one it
paints thin, broken cloud and haze salmon: on 2026-11-20 at 01:00, at dawn
over the southern Indian Ocean (east of 60°E, south of 15°S), the brightest
tenth of cloud (display level over 140) runs 2 levels redder than blue at a
sun of 64°, 14 at 70–72° and 18 to 24 from 72° to 84°, where the grey fade
ends it; the mean cast is 4 to 7. CIRA's Meteosat-9 shows that cloud grey.
Cloud and haze now lose their tint, keeping their brightness, as the sun
goes from 64° to 76°, where the mean colour runs from 10 to 20% (dark sea
keeps its blue): the brightest tenth is at most 5 redder, and the mean at
76–84° 4 bluer, from FCI's tone curves. The same fade on every pixel greyed
the dusk sea where MTG-I1 keeps it blue. dusk-seviri went from 9.7, 10.9,
12.5 to 9.6, 10.9, 12.5; day-seviri, snow-seviri, glint-seviri and
h-day-seviri, under a higher sun, are unchanged.

Since 2026-11-22 that fade acts over water only. Over land it greyed the
dawn: on 2026-11-22 India at 02:00 and Arabia at 04:00 were a bright,
colourless sheet in the Mosaic, display level about 150 with a chroma of 3
to 5 under a sun of 72–80°, where CIRA's Meteosat-9 shows 56–86 with 6 to
21. Under a low sun the corrected bands of desert and hazy fields rise as
cloud's do (the table's mean colour over land from 16% at 60° to 34% at
78°), and the fade took 55–87% of India's tint at 02:00 and half of
Arabia's at 04:00; the other fades hardly touch that land before 80°.
Untouched, the table gives Arabia's desert at 04:00 (sun 77°) 172, 146,
123, its colour at 06:00 (172, 147, 123). Two ways to tell the cloud the
fade is for from such land, by SEVIRI's bands under a sun of 60–80°:
1.6/0.8 µm is 1.19–1.38 over Arabia's desert (5th to 95th percentile),
0.71–1.05 over the salmon cloud of 2026-11-16 01:00 and 0.15–0.99 over
cloud on land, but 0.45–1.03 over India's hazy fields, so it would spare the
desert only; the land mask spares both. Bright cloud over land keeps a
near-grey colour from the table (median red 1.0 to 1.5% above blue). On
2026-11-16 01:00, 1 of 1.58 million pixels moves by more than 2 levels.
Pixels of the full Recipe moved by more than 8 levels over 35–100°E,
2–40°N: 4.2% at 02:00, 2.6% at 03:00, 10.3% at 04:00.
India at 03:00 is still pale: under a sun of 60–72° its colour is CIRA's (a
blue-green haze; over central India G−R +8, B−R +2 against +10, +6) but
about 40 levels brighter (116–124 against 73–85), and brighter than ours at
a high sun. No fade acts there; it is the table's colour of November's haze
under a low sun.

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
- Settings: dask `array.chunk-size` of `32MiB`, `DASK_NUM_WORKERS` as many as the step's cores,
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
- satpy and its libraries print the same few lines on every render. Each was
  traced to its cause, the first six on a night-time GOES-East Disk on
  2026-11-13 and the rest on 2026-11-22 (below), and none changes the image,
  so the render filters exactly these (`KNOWN_WARNINGS` and
  `KNOWN_LOG_LINES` in `georing.render`) and shows whatever else is said.
  The dask ones are filtered by message wherever dask raises them, so a
  division of our own that goes wrong would be hidden too.
- "The following datasets were not created and may require resampling": satpy,
  twice, because the render loads the Recipe in two stages.
- "No sensor name specified in HDF5 file": pyspectral, reading a sensor's
  response file for the Rayleigh correction. "No 'platform_name' in HDF5
  file" likewise, for Meteosat-9's (`rsr_seviri_Meteosat-9.h5`), which keeps
  the older `platform` and `sat_number`; pyspectral reads the name from
  those.
- "divide by zero" and "invalid value" in `trollimage/xrimage.py`: satpy's own
  low-cloud enhancement colours with a one-colour palette, and trollimage
  works out a scale for its metadata from it.
- "The specified chunks separate the stored chunks": xarray, when satpy opens
  the two static images. The warped city lights are kept; the land mask is
  warped again on every render.
- "cannot convert float NaN to integer": satpy's image reader, on a static
  image that declares no nodata value. It leaves the data unmasked, which is
  what the Recipe wants.
- "divide by zero encountered in divide" (dask): satpy's SEVIRI reader turns
  a radiance into a brightness temperature through `1 / radiance`. On
  Meteosat-9's 10:00 Disk of 2026-11-22, 1,911 pixels of its 3.9 µm band
  had a radiance of 0, all seen 76.5° to 91° from vertical (median 88.8°),
  far outside the strip the Mosaic takes from it.
- "invalid value encountered in divide" (dask): satpy's background
  compositor divides by the joined opacity, 0 where both layers are
  transparent, and fills those pixels on the next line. Seen on Meteosat-9.
- "invalid value encountered in divide" and "Mean of empty slice" (satpy,
  `composites/resolution.py`): the ratio sharpening divides the fine band by
  the coarse one and replaces what is not finite by 1, and averages 2×2
  blocks with `nanmean`, which off the Disk are all NaN and stay NaN. Read
  off satpy's code; the stack prints them during the Himawari and MTG-I1
  renders.
- Until 2026-11-22 every render of a day layer without an orbit (AHI's)
  printed "Actual satellite lon/lat not available", "Actual satellite
  altitude not available" (satpy) and "You will likely lose important
  projection information" (pyproj): the Recipe gave satpy the grid's
  satellite as the projection centre, read off a PROJ string. It now reads
  it off the grid's parameters and gives it as the nominal position, which
  satpy takes without a warning; the view angles are the same.
- Not filtered: dask's "All-NaN slice encountered" from `nanmax`, printed now
  and then during the Meteosat-9 render. It did not recur on the Disks
  traced, so its cause is not known.
- The trace has to run as a step does: a render in a process that imported
  dask before `DASK_ARRAY__CHUNK_SIZE` was set ran with 128 MiB chunks and
  printed neither divide warning.
- "invalid value encountered in log": the 3.9 µm brightness temperature is NaN
  where the radiance is negative. That was 477 of 23 million pixels, all on
  cold cloud tops (median 200 K at 10.4 µm), and the night layer shows them as
  white high cloud. The night layer's only NaN pixels, 44 of them, lie exactly
  on the Disk's rim, which the join cuts off.

**Joining satellites**
- The Mosaic computes each satellite's view angle on its own grid, on a
  spherical Earth, from the Rendering's projection and from where the
  satellite actually was (its tags), taking the larger of the two (above,
  under "Meteosat IODC").
- `satpy.modifiers.angles.get_satellite_zenith_angle` gives the same angle,
  but only on a Disk's grid.
- The Renderings are warped to the Mosaic grid with GDAL (bilinear), in
  2048 px chunks, and not with satpy's resamplers.
- How visible a Seam is, measured: along every Seam on the whole Mosaic at
  1/16, the mean colour difference between the two neighbours' own
  Renderings at the same ground (the Renderings read decimated and
  reprojected; GDAL's warped view of a whole south-up or mirrored grid at
  that scale returned nothing for MTG-I1 and Meteosat-9). On 2026-11-17, from
  the same Renderings:

  | Slot | resolution rule and glare penalty | steepest view (ADR 0005) |
  |---|---|---|
  | 02:00 | 22.3 | 19.5 |
  | 03:00 | 24.0 | 21.4 |
  | 14:00 | 22.6 | 18.1 |

  By Seam the largest change is Himawari and Meteosat-9 at 02:00 and 03:00,
  52.0 and 58.4 to 30.7 and 28.7; the two GOES stay at 11 to 20, GOES-West
  and Himawari at 11 to 29 (unchanged), MTG-I1 and Meteosat-9 17 to 24.
  What is left is the two sensors' own difference and Meteosat-9's made-up
  colour. By eye, the steepest view removes MTG-I1's burnt dawn limb and
  white Madagascar (03:00), Himawari's hazy edge at 75°E (02:00, 03:00) and
  MTG-I1's hazy dusk limb over East Africa (14:00), which the glare penalty
  had left. White remains toward the poles, where every satellite sees
  steeply. The glare penalty tried before it (ADR 0005, considered options),
  which cost 0.03 s per chunk and satellite: at 18:00 on 2026-11-17 it
  drew the GOES-East and MTG-I1 Seam as a hard line over the Atlantic.
- Glint cut off at a Seam, 2026-11-19/20: GOES-East's grey glint centred on
  the GOES Seam at 106°W at 21:00, MTG-I1's grey-beige band off Brazil at
  18:00 and Meteosat-9's beige disk south of India at 01:00, each ending in
  a straight line where the neighbour's sea is blue. On clear sea at 21:00
  the darkest tenth of GOES-East's pixels reads 98 levels within a glint
  angle of 5°, 75 at 15–20°, 47 at 20–25°, 29 at 25–30°, 20 at 30–35° and
  7 beyond 40°; GOES-West's 110, 77, 59, 39, 28 and 25: glint shows to
  about 35°. A satellite's view now counts as up to 20° more slanted at the
  Seam, full within 30° of glint, none beyond 45°, faded in over the sun's
  first 5° above the horizon. Joined from the real Renderings, all three
  patches give way to the neighbour's blue sea with no line (10° left the
  cut, 30° from 30–45° also took the faint rim). Over the Earth seen at
  0.1°, every three hours on 2026-11-19, it moves 1.0–2.9% to a view more
  than 0.5° slanted and 0.1–1.0% more than 10°. The feather narrows where the glint's rise
  adds to the view angle's: under 150 km on up to 4% of the Seams'
  length, 98 km at the narrowest, against 254 km at the 5th percentile
  without; no line showed in the three Joins. A ramp of 25–50° or 20–55°
  narrows it as much. The glint angle, from the sun's direction (pyorbital)
  and the satellite's actual position on a sphere, agrees with the
  Recipe's to 0.02°. It is worked out only where the sun is up and more
  than one satellite sees the chunk, at 0.5 s and 170 MB a chunk: the whole
  21:00 Slot, five Renderings on 32 threads, joined in 267 s against 265
  without it.
- Glint edge at a moved Seam, 2026-11-20: in the published Slots the moved
  Seam lies in the glint, and the 5° feather drew a soft straight edge across
  it. Clear sea (the 20th percentile of 1° columns, 4–16°S) at 22:00 fell
  from 112 levels at 169°E to 34 at 174°E, 25 in the steepest degree, where
  Himawari's glint met GOES-West; at 16:00 a band of MTG-I1's glint began at
  28°W. Widening only the clear neighbour's feather, by 1° per degree of
  penalty between the two, took the glint down gradually but left that
  steepest degree: at equal rank the two still split the pixel evenly.
  Dropping a glinting view's weight with its penalty as well, to 0.2 at the
  full penalty, moves most of the pixel to the neighbour there: the steepest
  degree fell to 14 levels at 22:00 (to 15 with 0.5) and from 20 to 8 on the
  GOES Seam at 21:00 on 2026-11-19, and by eye the edges are gone. Clouds in
  the wider feather show faint ghosts at full resolution, none doubled: one
  view carries most of each pixel. Widening the glinting view's side as
  well, by half as much, would by the weights (not joined) give the glint
  about 40% of the pixel at its centre, where the neighbour took the place. The whole 21:00 Slot changed by more than 2 levels on 1.2% of the
  Earth seen, all near glint, and joined in 302 s against 265: the penalty
  is now worked out for every satellite that sees a chunk, and a Seam may
  reach 25° of view angle where there is glint.

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
  are not unique. The key names the Slot, the Disks it would add and the six hours
  it was asked in, so the same rebuild is queued once in six hours and a
  different one still can be. `work_queue_name=` puts the run in a queue
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

What holds now, with the Recipe, the 5° Seam and only the Mosaic published,
measured with the four Disks of then unless Meteosat-9 is named:

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
