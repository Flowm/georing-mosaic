# Plan

Agreed in a design session and confirmed by the owner on 2026-11-11. Milestones
one to four of "Build order" are built: the compose stack builds a Slot every
hour, `georing-slot` builds one from a shell with the same flow,
`georing-backfill` queues past Slots, and `georing-compare` judges the Recipe
on the Comparison scenes.

Terms in capitals are defined in `GLOSSARY.md`. Reasons for the five decisions
that were real trade-offs are in `docs/adr/`; this file does not repeat them.
What was looked up and measured on the way, such as the data sources, the
behaviour of satpy, Prefect and the COG driver, and what a Slot costs, is in
[notes.md](notes.md).

## Decisions

### Inputs

- **Satellite set:** GOES-East (GOES-19), GOES-West (GOES-18), Meteosat at 0°
  (MTG-I1, also called Meteosat-12), Meteosat over the Indian Ocean
  (Meteosat-9, position `meteosat-iodc`, since 2026-11-14) and Himawari
  (Himawari-9). The set is a setting. Meteosat-9 fills the India seam, where
  the others view the ground at about 80° (ADR 0005), and takes 23 to 93°E,
  where it sees most steeply (ADR 0005).
- **Slot:** a full clock hour. A Slot uses each satellite's scan that starts on
  that hour (ADR 0002).
- **No detail is discarded in processing.** The 0.5 km red band is used, so
  Meteosat at 0° needs both of its collections (normal and high resolution).
  The one exception is Meteosat-9's 1 km HRV band, which covers part of its
  disk only (ADR 0005); see "Open items".
- **City lights:** NASA's yearly Black Marble from NOAA-20 (VJ146A4, 2025),
  radiance and a land mask at 500 m, which the flow builds once into a COG
  under the work directory with the owner's NASA Earthdata login, and which
  the Recipe puts on each satellite's finest grid (ADR 0006). Black Marble
  has no tiles south of 70°S; there the land comes from the GSHHS mask.

### Products

- **Each Slot publishes one file, its Mosaic.** The four Renderings were
  published too at first, as COGs in each satellite's own view at 0.5 km.
  They were taken out on 2026-11-12: satvis, the one consumer, reads only the
  Mosaic, and they were half the storage and four encodes per Slot.
- **Rendering:** the satellite's own geostationary projection at its finest
  resolution, 0.5 km (3 km for Meteosat-9), written lossless to scratch, where
  the Mosaic is joined from it and compressed once.
- **Mosaic:** Web Mercator at the resolution of zoom 8 (611 m per pixel at the
  equator, 65,536 px across) in 512 px tiles aligned to the web tile grid
  (ADR 0001), lossy WebP at quality 90 (ADR 0004). The full-resolution tiles
  are the 512 px web tiles of level 7, and each overview is the level below.
- **Recipe:** our own satpy composite, `georing`, under `src/georing/satpy`.
  It keeps the structure of satpy's `geo_color` and is tuned toward CIRA's
  GeoColor ([Miller et al.
  2020](https://journals.ametsoc.org/view/journals/atot/37/3/JTECH-D-19-0134.1.xml))
  on the tuning set of Comparison scenes and checked on the holdout set. What
  it changes and what is left is in the notes, under "Recipe". It departs
  from CIRA on purpose in one place: where a satellite looks into a low sun's
  reflection over the sea, along its limb at dawn or dusk, CIRA's day layer
  burns out to white and ours gives way to the night layer. The owner
  judges when it is close enough; that judgement is open.
- **Meteosat-9's day colour** is looked up in a table of the colour its
  neighbours show for each combination of SEVIRI's red, 0.8 µm and 1.6 µm
  bands, made by `georing-fit-colour` from what each pair sees at the same
  time: MTG-I1 everywhere, and Himawari over clear land, which brings South Asia's
  green (the notes, under "SEVIRI", say why not its sea). It then takes
  FCI's tone curves (ADR 0005). Where the table never saw the bands the
  colour fades to a neutral grey: from a view of 58° to 66°, a sun of 80° to
  88°, the brightest band from 110 to 130%, and over water a glint angle
  from 22° to 12°. Before that, cloud and haze lose their tint, keeping
  their brightness, as the sun goes from 64° to 76°. The grey is the uncorrected
  0.8 µm band divided by the sun taken no lower than 60°. By night its low-cloud ramp starts 2.6 K
  higher over land and 3.3 K over sea than the other sensors': SEVIRI's
  10.8 − 3.9 µm difference runs that much above FCI's over the same clear
  ground. How both were measured is in the notes, under "SEVIRI".
- **Comparison scenes:** a tuning set of twenty-one, seventeen on
  2026-11-10 and the low-sun, two limb and Meteosat-9 glint scenes on 15, 16
  and 19 November, which the Recipe is
  fitted to, and a holdout set of seven at other places, which is only
  measured: GOES-East's three on 2026-09-14, Meteosat's two on 2026-11-14
  and Meteosat-9's two on 2026-10-01. Five more holdout scenes, Himawari's
  three and two of Meteosat's on 2026-09-14, were dropped on 2026-11-18:
  SLIDER no longer held their references, so Himawari has none now. They are
  listed in the notes, under "Recipe". The reference is CIRA's GeoColor from
  SLIDER, in each satellite's own view at 1 km (3 km for Meteosat-9).
  `georing-compare` renders each scene and writes it beside its reference.
  For Meteosat-9 the reference is a check of the look only: its colour
  follows MTG-I1, not CIRA.
- **Seam:** a feathered band, written in our own code. satpy's multi-scene
  blend is experimental and a wide weighted average shows high clouds twice.
  A pixel comes from the satellite that sees it most steeply, by the view
  angle alone (ADR 0005), so the Seams lie halfway between the satellites,
  where both see the ground at about the same angle. The band is where the
  two view angles differ by less than 5°, about 470 km on the ground between
  the two GOES. The width was chosen on the
  Slots of 2026-11-10 18:00 and 06:00 joined at 0.5°, 2°, 5° and 10°: 0.5°
  and 2° leave a line where the two satellites see haze, glint or dawn in
  different colours (off Brazil by day, at the date line at dawn, over India
  by day); 5° is the narrowest that turns each into a gradient; at 10° cloud
  is plainly doubled, most of all at 70°E. The mean gradient in the band falls
  to 0.92–0.97 of its value at 0.5° with 5°, and to 0.83–0.93 with 10°.
- **Limb:** a Rendering is not used where its satellite is more than 85° from
  vertical. Beyond that the pixels are smeared streaks. Its share fades out
  over the last 5° before that, so that where a neighbour takes over there
  is no line: near the poles both neighbours often see a place within 5° of
  each other, and a share cut off at 85° left hard arcs (north of
  Scandinavia at 2026-11-19 03:00, where MTG-I1 still had about 0.7 of the
  blend when it stopped). Where no neighbour sees the place, the Rendering
  keeps its colour to its limit. The angle is the
  larger of two: from where the satellite actually was during the scan,
  which the Rendering carries in its tags, and from its grid's nominal
  position on the equator. Meteosat-9's inclined orbit takes it up to about
  8° off the equator; the true position cuts what it did not scan, the
  grid's what its grid does not hold. The limit was tuned on
  real images like the Seam. Without Meteosat-9 this opens a gap around 70°E
  poleward of about 45° latitude; with it the gap there begins near 70°.
  Poleward of 76.5° no geostationary satellite sees any longitude. Where a
  satellite scanned nothing its Rendering is transparent, by night too, so a
  neighbour or the gap shows: Meteosat-9's scans miss rows at the ends of
  its grid, and its night layer drew them as opaque black (the notes, under
  "satpy").
- **Deadline:** a Slot builds as soon as all its Disks are present, typically
  from 14 minutes past the hour. At 35 minutes past it builds without any Disk
  still missing. The measurement behind 35 is in the notes, under "Arrival
  times".
- **Missing Disk:** the neighbours fill what they can see and the rest stays
  transparent. The catalogue records which Disks contributed. A Disk that
  arrives later causes the Slot to be built again from all its Disks, and
  replaced if that adds a Disk. Joining the late Disk with the published
  Renderings of the others would save about 12 minutes and 3 GB per rebuild,
  for about one Slot in ten; it was built first and taken out, because it
  was the most delicate path in the flow and made a rebuilt Mosaic from
  lossy copies. A rebuild replaces a Mosaic only by a better one: a rebuild
  that would lose a Disk, or add none, publishes nothing. It fetches the
  Disks the Mosaic lacks first and stops if none of them can be had, before
  downloading and rendering the others: in the EUMETSAT outage of
  2026-11-17/18 every rebuild took 24–30 minutes to find that out, and each
  pushed the next Slot of the hour back by up to 40 minutes. Imagery from
  another Slot is never used as a stand-in, and that includes the same
  satellite's scan at 10 minutes past: a possible later addition for GOES and
  Himawari, ruled out for Meteosat by ADR 0002.

### Flow

- **One Prefect flow per Slot,** with the Slot time as its parameter, scheduled
  at 10 minutes past each hour. The same flow serves backfills and rebuilds.
  A scheduled run builds the hour it was scheduled in, however late it
  starts: after an outage the worker runs the runs it missed, and each must
  build its own hour. A Slot that has not begun is refused.
- **One flow, named after the project.** The flow is `georing-slot`, and a
  run is named after its Slot, such as `georing-slot-20261111T2000Z`, so that
  it can be told apart on a Prefect server shared with other projects. There
  is no second flow for backfills: a backfill is runs of the same flow for
  past Slots. A run the scheduler creates ahead keeps Prefect's random name
  until it starts.
- **Steps:** per satellite a download step that polls once a minute until its
  files exist or the deadline passes, then a render step; then the Mosaic's
  join, encode and publish steps; then one index step. Each step that computes
  runs in a child process of its own (`georing.step`). A step that has not
  finished after 30 minutes (the slowest takes five) is killed, with whatever
  it started, and counts as failed; a download after five minutes (the
  slowest takes 80 s), so that a source in trouble holds a Slot's downloads
  no more than five minutes past its deadline. In the EUMETSAT outage of 2026-11-17/18
  Slots ran 40 to 48 minutes. A step inherits none of the EUMETSAT and
  bucket credentials and has only those it is handed: the two Meteosat
  downloads and the look-back for late Disks get the EUMETSAT key.
- **One Disk's failure does not cost the Slot.** A Disk that cannot be
  downloaded or rendered is left out and recorded as missing.
- **Scratch is removed when a run ends,** failed or not. What a run that was
  killed leaves is removed by a later run once nothing has touched it for
  three hours.
- **Late Disks:** after its own Slot, the run of the hour looks back over the
  last 48 Slots and queues a rebuild for each one that
  lacks a Disk its source now holds. A Slot with no Mosaic at all, whose run
  failed or never started, lacks every Disk; it counts for six hours, and only
  if an older Mosaic exists, so neither a new deployment nor a long outage
  builds days of Slots unasked. A longer gap is a backfill. The same rebuild
  is queued once in six hours: a source can answer a search but fail the
  download, and a rebuild queued every hour for each of 48 Slots would fill
  the catch-up queue, while one queued once was never tried again. A source that cannot be asked is
  asked again next hour and does not fail the run. The sources are asked in a
  step of its own, under the time limit, and never from the flow's own
  process. The setting `rebuild_late` (`GEORING_REBUILD_LATE=false`) turns
  the looking back off, for a source's outage; a backfill then fetches what
  is lacking.
- **One flow run at a time:** the worker starts with `--limit 1`.
- **Catching up never holds up the Slot of the hour.** Rebuilds and backfilled
  Slots wait in a work queue of their own, `catch-up`, which the worker serves
  after the default one. A run that has started is not interrupted, so a
  long rebuild still delays the next Slot; a rebuild that adds nothing now
  ends after its first downloads.
- **Backfill:** the command `georing-backfill START [END]`, run in the worker
  container, queues a run of `georing-slot/hourly` for every Slot in that time
  that is not done or lacks a Disk, newest first, in the catch-up queue. With
  `--force` it queues every Slot, to build each again whatever it has. It was
  a flow of its own at first; that put a second flow on the server whose runs
  built nothing. Beside the hourly run there is room for one or two caught-up
  Slots an hour.
- **Renders run one at a time,** in the order their Disks arrive, so a late
  Disk does not hold up the others. Each render uses all eight cores, so two
  at once would finish no sooner, and the Meteosat render peaks at 21 GB.
  Meteosat-9's render takes 5 s and 1.5 GB.
  On a larger machine the setting `parallel_renders`
  (`GEORING_PARALLEL_RENDERS` in `.env`) runs several at once. The worker
  then uses eight cores for each, as one pool: a render keeps to eight
  threads, the join and encode use them all. The compose file sets no CPU or
  memory limit: every step pins itself to that pool.
- **No push notifications.** The AWS and EUMETSAT feeds exist but are not used.

### Catalogue and storage

- **Static STAC,** written as JSON files beside the Mosaics: a root
  `catalog.json`, one Collection `mosaic` that lists every Item, and one Item
  per Slot. A reader has every Slot after two requests. Until 2026-11-13 the
  Collection listed one catalogue file per day, which cost a reader a request
  per day and the code a walk over the folders. The Item records which Disks
  the Mosaic was built from, which it lacks, and the attribution each provider
  asks for.
- **Each item link in the Collection carries its Item's `datetime`,** the
  Slot in RFC 3339 UTC (`2026-11-13T15:00:00Z`), so a client builds the
  timeline from `collection.json` alone. Consumers may rely on it. STAC 1.1
  allows Common Metadata on links, and its schemas check the field there. Before
  2026-11-13 a link carried no time, so a client had to read the Slot off the
  file name or fetch every Item. If Slots ever get `start_datetime` and
  `end_datetime`, those go on the links the same way. Item ids, file names and
  `latest.json` stay as they are, so a client that reads the name still works.
- **`latest.json`** names the newest Slot that has a Mosaic, with the Disks it
  was built from and the ones it lacks, for clients that want only that, and
  so a consumer can tell when the data is stale.
- **Links are relative** and Items sit beside their products, so the tree can
  be served from any prefix. The layout is in `src/georing/catalogue.py`.
- **Each Item carries the attribution** its data providers ask for.
- **The catalogue is the record of which Slots are done** (ADR 0003).
- **The output location is a URL setting,** `output_url`: a path for a host
  directory, the default, or `s3://bucket/prefix` for a bucket (Cloudflare R2
  is the one meant). `georing.storage` holds the two behind one interface.
  Paths start with the product and then the date: `mosaic/YYYY/MM/DD/…`.
- **A bucket is reached with settings of our own,** `GEORING_S3_ENDPOINT_URL`,
  `GEORING_S3_ACCESS_KEY_ID` and `GEORING_S3_SECRET_ACCESS_KEY` in `.env`, not
  with the `AWS_` variables: those would also reach the anonymous client that
  downloads from NOAA's buckets, and an endpoint set there sends the
  downloads to the wrong host. The key needs to read and write objects; it
  needs no delete, because an upload to a bucket shows up only when complete
  and nothing is renamed.
- **JSON in a bucket is stored with `Cache-Control: no-cache`:** every
  catalogue file is rewritten as Slots arrive.
- **The pipeline deletes no product.** How long Mosaics are kept is for
  whoever runs it: a lifecycle rule on a bucket, or nothing at all for a
  directory, which is meant for testing and grows by up to 10 GB a day.
- **The index step lists the store and rewrites the Collection, the root and
  `latest.json`.** The list is read off the store each time, so it follows a
  rebuild, a backfill and whatever a lifecycle rule removes. Its cost grows
  with what is kept: 124 bytes of list and two keys to look through per Slot,
  which is 1.1 MB and 18 list requests after a year kept in full. An Item is
  written after its image and never again, so an Item means both are there;
  where a lifecycle rule removes them, one rule for the `mosaic/` prefix keeps
  it so.
- **Raw downloads** live on the worker's scratch disk and are removed when
  their Slot finishes.

### Hosting and packaging

- **Compose file with two services:** the Prefect server as a single container
  on SQLite with no Redis, and the worker (ADR 0003).
- **Worker size:** 8 cores and 32 GB of RAM. Milestone one built both test
  Slots inside that: 23 minutes per Slot and a peak of 21 GB.
- **Python 3.14.** Prefect supports 3.15, but `pyresample`, `pykdtree`, `h5py`,
  `numcodecs` and `bottleneck` publish wheels only up to 3.14. satpy 0.60.0's
  own tests stop at 3.13, but it built both test Slots on 3.14.7; the two
  workarounds that needed are in the notes, under "Python 3.14".
- **`uv`** for dependencies, and one Docker image for the worker. The server
  uses Prefect's official image at the same pinned version.
- **satpy is pinned to a release.** Its static files are fetched when the image
  is built, so a run downloads only satellite data.
- **Settings** are what differs between places it runs: the satellite set, the
  output URL and the bucket's address and key, the work and static
  directories, the cores a render uses and how many renders run at once.
  Their defaults are in `src/georing/settings.py`, and an environment variable
  named `GEORING_` and the setting overrides each; a deployment keeps them in
  `.env`. What nothing
  varies is a constant beside the code that uses it: the Seam width, the limb
  limit, the WebP quality, the deadline and the step time limit.
- **The EUMETSAT key and secret** come from the environment variables
  `EUMETSAT_CONSUMER_KEY` and `EUMETSAT_CONSUMER_SECRET`, kept in a `.env`
  file that git ignores (`.env.example` shows the shape).
- **Deployments** are declared in `prefect.yaml` and registered when the worker
  container starts: `georing-slot/hourly`, on the schedule.
- **The worker runs as the owner of the output directory,** not as root, so
  the products in a host directory belong to that user: user 1000, unless
  `GEORING_UID` and `GEORING_GID` in `.env` name another.
- **Names:** the repository is `georing-mosaic`; the Python package, Docker
  image and bucket prefix are `georing`.
- **Alerting:** none in the first version beyond the Prefect UI.
- **Licence:** MIT, in `LICENSE` since 2026-11-12. The repository is private at
  first.

### Consumer

satvis reads the Mosaic directly from the bucket. That is a separate change in
the satvis repository; what it needs is in the notes, under "COG, writing and
reading".

## Build order

1. **One Slot as a plain script, without Prefect.** Done on 2026-11-11: all of
   these held then. The report of each step was removed once its figures
   were in the notes.
   - For one daytime Slot and one night-time Slot it writes four Renderings and
     a Mosaic to a directory.
   - It reports, per step, wall time, peak memory, bytes downloaded and output
     file size.
   - The Mosaic's tiles are confirmed aligned to the web tile grid at every
     overview level.
   - It ran on a machine no larger than 8 cores and 32 GB, or the report says
     what size it needed.
   - Each estimate is replaced by its measurement; they are in the notes,
     under "Measurements".
2. **Comparison scenes** against the reference products, and the Recipe tuning
   that follows from them. Built on 2026-11-11; the owner's judgement is open.
3. **The Prefect flow and the compose file.** Built on 2026-11-11. The stack
   built the Slot of 09:00 UTC that day on its schedule: started at 09:10,
   done at 09:32, with all four Disks.
4. **Backfill.** Built on 2026-11-11. A backfill of 04:00 and 05:00 UTC built
   both Slots, newest first.
5. **The satvis layer,** in the satvis repository.

## Open items

- **EUMETSAT licence.** Confirm the reading in ADR 0002 with EUMETSAT before
  the product is public. The policy lists hourly SEVIRI data, Meteosat-9's
  among them, as Core data like FCI's (notes, "Licences and attribution").
- **Meteosat's late cluster.** Find out whether products stamped near 30 past
  were already downloadable near 14 past: try the download at 15 past on such
  a Slot, or poll the search API for several hours (about one such scan every
  two hours). If they were, nearly every Slot is complete by 17 past and the
  deadline can come down from 35.
- **Cross-origin range requests on R2.** Whether a public R2 bucket needs extra
  CORS settings for them is unknown.
- **Meteosat render memory.** It peaks at 21 GB where the other three peak
  at 11 to 12 GB, and the cause is not found. With four dask workers it is
  14 GB but takes more than twice as long.
- **The owner's judgement of the Recipe.** The side-by-side images are in
  `work/comparison/georing/` after `georing-compare`, those of the Recipe
  before it was tuned in `work/comparison/baseline-4beb0f0/`. The holdout set
  says the night changes and the twilight compositor hold on another day;
  Himawari's sun glint and snow miss their targets. On 2026-11-15 the owner
  judged the twilight at 78–84° closest to CIRA's, and named two gaps: low
  cloud and sea past 84°, which CIRA draws with ProxyVis over the ocean, and
  the city lights, then 3 km and finished on the infrared grid. The lights
  are now 500 m (ADR 0006); ProxyVis is open. What still differs from CIRA is
  listed in the notes, under "Recipe".
- **The references are not kept.** SLIDER holds some weeks, and the copies
  under `work/comparison/reference/` are not in git: they are CIRA's images.
  On 2026-11-15 the local `work/` was deleted and five holdout references
  (2026-09-14, Himawari and Meteosat) were lost for good; their scenes were
  dropped. On 2026-11-18 every remaining scene's reference was in
  `work/comparison/reference/`. Decide where the Comparison scenes'
  references and Disks are to live, and whether Himawari gets holdout
  scenes again, on a day SLIDER still holds.
- **The attribution lists the EUMETSAT line twice** when both Meteosats
  contribute.
- **The two sides of a Seam differ in colour.** The 5° feather turns the line
  into a gradient; the difference itself remains. Off Brazil at 18:00
  Meteosat's side of the sea is grey-beige and GOES-East's blue; at the date
  line at dawn Himawari's side is grey and GOES-West's blue; at 70°E, viewed
  at a low angle from both sides, haze differed by day until Meteosat-9 came
  between them. Each satellite looks at
  the same sea from another side of the sun, so the Recipe would have to
  correct for the direction of view to close it. The feather was chosen on two
  Slots between 32°S and 32°N. Poleward of 50° it was looked at on the 18:00
  Slot only: the Seams are gone there too, and the Mosaic covers the same
  pixels as at 0.5°.
- **The catalogue is not checked against the STAC schemas in the tests.** The
  tests follow every link and check the fields we set. On 2026-11-13
  `stac-validator validate --recursive` passed on a catalogue of three Slots
  written by the index step (the Catalog, the Collection and three Items, all
  valid STAC 1.1.0). It fetches the schemas over the network, so it is not
  part of the tests.
- **Output to a real bucket.** The compose stack has written to a Cloudflare
  R2 bucket since 2026-11-12. On 2026-11-13 it built the eleven Slots from
  03:00 to 13:00 on its schedule, each with all four Disks, in 14.5 to 16.8
  minutes with two renders at once on 32 CPUs. The publish step of the 13:00
  Slot took 5 s for a Mosaic of 328 MB. Read back through the S3 interface on
  2026-11-12, a Mosaic answered a byte-range request with 206 and an
  `If-Match` with a wrong ETag with 412. Not yet checked: reading it over the
  bucket's public address and from a browser (cross-origin), and lifecycle
  rules.
- **Meteosat-9's HRV band.** SEVIRI's 1 km broadband band could sharpen its
  part of the Mosaic where it covers the disk, at the cost of a step in
  sharpness where it ends. Not tried.
- **Meteosat-9's colour against CIRA.** Its Comparison scenes differ from
  CIRA's Meteosat-9 GeoColor by 11 to 29 levels by day: CIRA paints its sea
  grey and its land greener than MTG-I1 shows them. By night they differ by
  4 to 26. Whether the made-up colour is close enough at its Seams is the
  owner's judgement, with the Recipe's.
- **Meteosat-9's colour table** was made from MTG-I1 on five Slots, three
  in November and two in September, and Himawari's clear land on six. Snow is
  thinly covered, and the hazy Arabian Sea stays salmon in the morning: the
  table cannot tell pollution haze from dust. A table made from more seasons would tell whether it
  holds through the year.
- **Who serves the Indian Ocean next.** Meteosat-9 is old and serves the
  Indian Ocean as EUMETSAT's "best effort". When it is replaced, the new
  satellite's bands decide whether its colour table still applies.
