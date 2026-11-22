# georing-mosaic

Hourly colour imagery of the whole Earth, made from the raw scans of five
geostationary satellites. Each hour it downloads one full-disk scan per
satellite, renders each in colour (true colour by day, infrared cloud over
city lights by night) and joins them into one global image.

It is a Python pipeline: [satpy](https://satpy.readthedocs.io) renders,
[Prefect](https://docs.prefect.io) runs it every hour, and the output is
Cloud Optimized GeoTIFFs with a static STAC catalogue, in a directory or an
S3 bucket.

## What it makes

For each hour, called a **Slot**, one **Mosaic**: the whole Earth in Web
Mercator at 611 m per pixel (65,536 px across), as a WebP-compressed COG of
280 to 420 MB. It is stored so that its internal tiles are the standard web map
tiles, and a client can read one tile with one byte-range request.

Beside the Mosaics lies the catalogue:

```
catalog.json                      the STAC root
latest.json                       the newest Slot that has a Mosaic
mosaic/collection.json            the list of every Mosaic
mosaic/2026/11/11/<id>.tif        a Mosaic, with its Item <id>.json
```

Each Item link in `collection.json` carries the Item's `datetime`, so the list
of Slots can be read from that one file.

Nothing is ever deleted; how long products are kept is up to you.

The words Slot, Disk, Recipe, Rendering, Mosaic and Seam have exact meanings
here; [GLOSSARY.md](GLOSSARY.md) defines them.

## The satellites

| Position | Satellite | Below it | Source |
|---|---|---|---|
| `goes-east` | GOES-19 | 75.2°W | NOAA's open bucket on AWS |
| `goes-west` | GOES-18 | 137.0°W | NOAA's open bucket on AWS |
| `himawari` | Himawari-9 | 140.7°E | NOAA's open bucket on AWS |
| `meteosat-0` | Meteosat-12 (MTG-I1) | 0° | EUMETSAT Data Store, with a free key |
| `meteosat-iodc` | Meteosat-9 | 45.5°E | EUMETSAT Data Store, with the same key |

Meteosat-9 covers only the strip around India, about 63 to 75°E, where the
others view the ground at about 80° from vertical. Its imager is 3 km and has
no blue or green band, so its day colour is looked up in a table of what
MTG-I1 and Himawari show of the same ground.

Each Slot uses the scan that starts on the hour. The scans arrive between 11
and about 15 minutes past, Meteosat's sometimes near 30 past. A Slot is built
without a Disk that has not arrived by 35 past, and rebuilt when it does.

## Run it

You need Docker, 8 CPUs, 32 GB of memory and a disk with room to grow: the
Mosaics in `./out` take up to 10 GB a day, and a build does not start with
less than 40 GB free. A Slot is about 3 GB of download and takes about 17
minutes to build.

```bash
cp .env.example .env        # then put in the EUMETSAT key and the Earthdata login
mkdir -p out
docker compose up -d --build
```

The worker writes `./out` as user 1000. If `id -u` shows another number for
you, set `GEORING_UID` and `GEORING_GID` in `.env` first.

The worker then builds a Slot at 10 past every hour and writes to `./out`.
The Prefect UI at <http://localhost:4200> shows each run and its steps.

Without a EUMETSAT key each Slot waits until 35 past for the two Meteosats
and is then built from the three other satellites, with the Meteosats' part
of the Mosaic empty. The key is free: <https://api.eumetsat.int/api-key/>.

To build one Slot by hand, or every Slot since a time that is not done:

```bash
docker compose exec worker prefect deployment run georing-slot/hourly -p slot=2026-11-11T21:00:00+00:00
docker compose exec worker georing-backfill 2026-11-11T04:00
```

## Settings

Everything in `.env` is described in [.env.example](.env.example). The ones
that matter most:

| Variable | What it does |
|---|---|
| `EUMETSAT_CONSUMER_KEY`, `EUMETSAT_CONSUMER_SECRET` | Meteosat's downloads |
| `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` | a NASA Earthdata login, for the city lights, which the first Slot builds once (51 GB of download, about 20 minutes) |
| `GEORING_OUTPUT_URL` | where products go: empty for `./out`, or `s3://bucket/prefix` |
| `GEORING_S3_ENDPOINT_URL`, `GEORING_S3_ACCESS_KEY_ID`, `GEORING_S3_SECRET_ACCESS_KEY` | the bucket, on AWS or a service that speaks S3, such as Cloudflare R2 |
| `GEORING_PARALLEL_RENDERS` | renders at once; two want 16 CPUs and 64 GB |
| `GEORING_REBUILD_LATE` | `false` stops the run of the hour from rebuilding earlier Slots that lack a Disk; `georing-backfill` still does |

Every other setting, with its default and its meaning, is in
[src/georing/settings.py](src/georing/settings.py). Each can be set as
`GEORING_<NAME>` in `.env`.

The pipeline deletes no product. In a bucket, set a lifecycle rule on
`mosaic/` for how long to keep them; the catalogue follows what it removes. A directory is meant for testing and is yours to clear.

## Work on it

Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check
```

The tests fake the heavy steps, so they run in two to three minutes. To build a
real Slot from a shell, with the same flow and a temporary Prefect server of
its own, and to judge the look against CIRA's GeoColor on fixed scenes:

```bash
uv run georing-slot 2026-11-10T18:00 --out out --work work
uv run georing-compare day night
```

A render takes about four minutes on eight cores and peaks at 22 GB, so run
one build at a time. Meteosat-9's colour table is remade with
`georing-fit-colour`; the notes say how.

## Where things are written down

- [GLOSSARY.md](GLOSSARY.md): the vocabulary.
- [docs/plan.md](docs/plan.md): what is decided and what is open.
- [docs/notes.md](docs/notes.md): what was looked up and measured.
- [docs/adr/](docs/adr/): the decisions that were trade-offs, with the
  alternatives they lost to.
- [AGENTS.md](AGENTS.md): how to work in this repository, for people and for
  coding agents.

## Data and attribution

The imagery is made from data of NOAA (GOES), the Japan Meteorological Agency
(Himawari, distributed by NOAA) and EUMETSAT (Meteosat). Each STAC Item
carries the attribution line its provider asks for; show it wherever an image
is shown. NOAA's attribution implies no endorsement by NOAA. Images that
include Meteosat carry "Contains modified EUMETSAT Meteosat data" with the
year.

The city lights are NASA's Black Marble; the look follows CIRA's GeoColor
(Miller et al. 2020), which is also the reference the Recipe is judged
against.

## Licence

The code is under the [MIT licence](LICENSE). The imagery is subject to its
providers' terms above.
