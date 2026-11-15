"""The city lights: NASA's yearly Black Marble from NOAA-20, as one global COG.

VJ146A4 holds a year of VIIRS Day/Night Band radiance, corrected for
moonlight and the atmosphere, at 15 arc seconds (about 500 m) in 10° tiles of
HDF5. The Recipe reads two of its layers: the radiance of the snow-free part
of the year from all view angles, and the land/water mask, which tells unlit
land from sea. ``build_city_lights`` downloads the tiles from LAADS and
writes those two layers as a Cloud Optimized GeoTIFF of two bands:

1. radiance in tenths of nW/cm²/sr, 0 where there is no light or no
   retrieval;
2. land as 100 and water as 0, so that averaging it onto a coarser grid
   gives the share of land in percent.

Where no tile lies (open sea) both are 0. LAADS wants a NASA Earthdata
login; the token for it is fetched with the user name and password.

The tiles are 51 GB, so each is turned into a small GeoTIFF as it arrives and
the HDF5 deleted. A build that is stopped goes on from the tiles it has.

The Recipe reads the COG through ``georing.lights.layer``.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

PRODUCT = "VJ146A4"
COLLECTION = 5200  # LAADS's number for collection 2
YEAR = 2025
RADIANCE = "AllAngle_Composite_Snow_Free"
LAND_WATER = "Land_Water_Mask"
# Of the mask's classes, 0 land and desert, 1 land, 2 inland water, 3 sea
# water and 5 coast: coast counts as land, so that a coastal town sits on it.
LAND_CLASSES = (0, 1, 5)
LAADS = "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content"
EARTHDATA_LOGIN = "https://urs.earthdata.nasa.gov/api/users/find_or_create_token"
LOGIN = ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD")
# 10° tiles of 2400 px: 240 px per degree.
TILE_PX = 2400
PER_DEGREE = 240
# Radiance is kept in tenths of nW/cm²/sr, which keeps the dimmest lit
# ground (0.5) apart from none and reaches 6553 nW/cm²/sr, brighter than any
# city's mean.
SCALE = 0.1
LAND = 100
# LAADS answers now and then with a 502, a 404 for a tile it lists and
# serves a minute later, or drops a connection: a tile is asked for again,
# after 10, 20, 40 and 80 s. Only a refused login is final.
TRIES = 5
PAUSE_S = 10
TILE_NAME = re.compile(r"\.h(\d\d)v(\d\d)\.")


def lights_path(work_dir: Path) -> Path:
    """Return where the city-lights COG of ``YEAR`` lives under ``work_dir``."""
    return work_dir / "lights" / f"{PRODUCT}.A{YEAR}.tif"


class NoLogin(RuntimeError):
    """The city lights must be built, and no Earthdata login was given."""

    def __init__(self, path: Path):
        super().__init__(
            f"{path} is missing, and building it needs a NASA Earthdata login: set EARTHDATA_USERNAME "
            "and EARTHDATA_PASSWORD in .env (free account at urs.earthdata.nasa.gov)"
        )


def earthdata_token(user: str, password: str) -> str:
    """Return a bearer token for LAADS: the account's own, or a new one.

    Earthdata Login keeps at most two tokens per account, each for 60 days;
    ``find_or_create_token`` hands back one that is still valid before it
    makes another.
    """
    basic = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        EARTHDATA_LOGIN, method="POST", headers={"Authorization": f"Basic {basic}", "User-Agent": "georing"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as failure:
        if failure.code == 401:
            raise PermissionError("Earthdata Login refused EARTHDATA_USERNAME and EARTHDATA_PASSWORD") from None
        raise


def build_city_lights(dest: str, secrets: dict[str, str] | None = None, threads: int = 4) -> str:
    """Write the city-lights COG to ``dest`` unless it is there; return its path.

    The Earthdata login comes from ``secrets`` (a ``.env``, for the tools),
    else from the environment (the flow's step, which is handed it as every
    secret is: ``georing.step``). A second build that starts meanwhile waits
    for the first, then finds the file.
    """
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out.with_name(out.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if out.exists():
            return dest
        env = {**os.environ, **(secrets or {})}
        user, password = (env.get(name) for name in LOGIN)
        if not (user and password):
            raise NoLogin(out)
        tiles = out.with_name(out.stem + ".tiles")
        tiles.mkdir(exist_ok=True)
        files = list_tiles()
        if any(not _tile_path(f["name"], tiles).exists() for f in files):
            token = earthdata_token(user, password)
            with ThreadPoolExecutor(threads) as pool:
                list(pool.map(lambda f: _tile(f, tiles, token), files))
        write_cog([_tile_path(f["name"], tiles) for f in files], out, threads)
        shutil.rmtree(tiles)
    return dest


def list_tiles(year: int = YEAR) -> list[dict]:
    """Return LAADS's entries for the tiles of ``year``: name, size and download link."""
    url = f"{LAADS}/details/allData/{COLLECTION}/{PRODUCT}/{year}/001"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "georing"}), timeout=60) as r:
        entries = json.load(r)["content"]
    return [e for e in entries if e["name"].endswith(".h5")]


def _tile_path(name: str, tiles: Path) -> Path:
    h, v = TILE_NAME.search(name).groups()
    return tiles / f"h{h}v{v}.tif"


def _tile(entry: dict, tiles: Path, token: str) -> None:
    """Download one tile, keep its two layers as a GeoTIFF and delete the HDF5."""
    path = _tile_path(entry["name"], tiles)
    if path.exists():
        return
    h5 = tiles / entry["name"]
    for attempt in range(TRIES):
        try:
            _download(entry, h5, token)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, IncompleteDownload) as failure:
            refused = isinstance(failure, urllib.error.HTTPError) and failure.code in (401, 403)
            if refused or attempt == TRIES - 1:
                raise
            time.sleep(PAUSE_S * 2**attempt)
    h, v = (int(n) for n in TILE_NAME.search(entry["name"]).groups())
    write_tile(*layers(h5), h, v, path)
    h5.unlink()


class IncompleteDownload(RuntimeError):
    """A tile arrived shorter than LAADS listed it."""


def _download(entry: dict, h5: Path, token: str) -> None:
    request = urllib.request.Request(
        entry["downloadsLink"], headers={"User-Agent": "georing", "Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=300) as src:
        if "html" in src.headers.get("Content-Type", ""):
            raise PermissionError(
                "LAADS answered with a web page instead of the tile: the Earthdata account may still "
                "have to accept LAADS's terms (log in once at ladsweb.modaps.eosdis.nasa.gov)"
            )
        with open(h5, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    if (size := h5.stat().st_size) != entry["size"]:
        h5.unlink()
        raise IncompleteDownload(f"{entry['name']}: {size} of {entry['size']} bytes")


def layers(h5: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a tile's radiance, in nW/cm²/sr with fill as 0, and whether each pixel is land."""
    import h5py

    def read(f, layer):
        found = []
        f.visititems(lambda name, obj: found.append(name) if name.split("/")[-1] == layer else None)
        if len(found) != 1:
            raise RuntimeError(f"{h5.name}: {len(found)} datasets named {layer}")
        data = f[found[0]][()]
        if data.shape != (TILE_PX, TILE_PX):
            raise RuntimeError(f"{h5.name}: {layer} is {data.shape}, not {TILE_PX} square")
        return data

    with h5py.File(h5, "r") as f:
        radiance = read(f, RADIANCE).astype(np.float32)
        land = np.isin(read(f, LAND_WATER), LAND_CLASSES)
    return np.where(np.isfinite(radiance) & (radiance > 0), radiance, 0), land


def encode(radiance: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Return the COG's two bands: radiance in tenths, held below the top of uint16, and land.

    The top value is kept free: ``layer.on_grid`` marks with it what a satellite cannot see.
    """
    level = np.clip(np.rint(radiance / SCALE), 0, np.iinfo(np.uint16).max - 1).astype(np.uint16)
    return np.stack([level, np.where(land, LAND, 0).astype(np.uint16)])


def decode(bands):
    """Return radiance in nW/cm²/sr and the share of land from 0 to 1, from the COG's bands."""
    return bands[0] * SCALE, bands[1] / LAND


def tile_transform(h: int, v: int):
    """Return the transform of tile ``hXXvYY``: h counts 10° east from 180°W, v south from 90°N."""
    from rasterio.transform import from_origin

    return from_origin(-180 + 10 * h, 90 - 10 * v, 1 / PER_DEGREE, 1 / PER_DEGREE)


def write_tile(radiance: np.ndarray, land: np.ndarray, h: int, v: int, path: Path) -> None:
    import rasterio

    part = path.with_name(path.name + ".part")
    with rasterio.open(
        part, "w", driver="GTiff", width=TILE_PX, height=TILE_PX, count=2, dtype="uint16",
        crs="EPSG:4326", transform=tile_transform(h, v), tiled=True, blockxsize=480, blockysize=480,
        compress="ZSTD", predictor=2,
    ) as dst:
        dst.write(encode(radiance, land))
    part.rename(path)


def write_cog(tiles: list[Path], dest: Path, threads: int) -> None:
    """Join ``tiles`` into one global COG at ``dest``. Where no tile lies, it is 0.

    The tiles go into a global GeoTIFF first, in blocks that divide a tile
    exactly, so that no block is written twice; the COG driver then copies it
    and adds the overviews.
    """
    import rasterio
    from rasterio.shutil import copy
    from rasterio.transform import from_origin
    from rasterio.windows import Window

    whole = dest.with_name(dest.stem + ".whole.tif")
    with rasterio.open(
        whole, "w", driver="GTiff", width=360 * PER_DEGREE, height=180 * PER_DEGREE, count=2,
        dtype="uint16", crs="EPSG:4326", transform=from_origin(-180, 90, 1 / PER_DEGREE, 1 / PER_DEGREE),
        tiled=True, blockxsize=480, blockysize=480, compress="ZSTD", predictor=2,
        bigtiff="YES", sparse_ok=True, num_threads=threads,
    ) as dst:
        for path in tiles:
            h, v = (int(n) for n in re.match(r"h(\d\d)v(\d\d)", path.name).groups())
            with rasterio.open(path) as src:
                dst.write(src.read(), window=Window(h * TILE_PX, v * TILE_PX, TILE_PX, TILE_PX))
        dst.update_tags(
            product=PRODUCT, year=str(YEAR), source=f"NASA Black Marble {PRODUCT} collection 2, LAADS DAAC",
        )
        dst.update_tags(1, layer=RADIANCE, units="nW cm-2 sr-1", scale_factor=str(SCALE))
        dst.update_tags(2, layer=LAND_WATER, meaning=f"land {LAND}, water 0")
    part = dest.with_name(dest.name + ".part")
    copy(
        whole, part, driver="COG", compress="ZSTD", predictor="YES", blocksize=512,
        overview_resampling="AVERAGE", bigtiff="YES", num_threads=threads,
    )
    whole.unlink()
    part.rename(dest)

