"""Join the Renderings of one Slot into a Mosaic on the web tile grid."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

EARTH_RADIUS = 6378137.0
HALF_WORLD = np.pi * EARTH_RADIUS  # Web Mercator spans +-20037508.34 m
TILE = 512
# The Mosaic's resolution is that of this standard web zoom level: 611 m per
# pixel at the equator, 65,536 px and 128 tiles of 512 px across. Its readers
# count on it (ADR 0001).
ZOOM = 8
# Half-width of the Seam: two satellites are feathered into each other where
# their view angles differ by less than this. Chosen on real Slots; see the
# plan.
SEAM_WIDTH_DEG = 5.0
# Beyond this view angle a Rendering is smeared along the limb and is left out.
MAX_VIEW_ZENITH_DEG = 85.0
# WebP quality of the published Mosaic (ADR 0004).
QUALITY = 90
CHUNK = 2048


def pixels_across(zoom: int) -> int:
    """Return the width in pixels of a whole-world image at web zoom level ``zoom``."""
    return 256 << zoom


def view_zenith(lat: np.ndarray, lon: np.ndarray, sat_lon: float, sat_height: float) -> np.ndarray:
    """Return the angle from vertical, in degrees, at which a satellite is seen.

    ``lat`` is a column and ``lon`` a row, both in degrees; the result is
    their grid. 90 and above means the satellite is below the horizon. The
    Earth is taken as a sphere, which shifts every satellite alike.
    """
    cos_g = np.cos(np.radians(lat))[:, None] * np.cos(np.radians(lon - sat_lon))[None, :]
    sin_g = np.sqrt(np.clip(1.0 - cos_g * cos_g, 0.0, None))
    ratio = EARTH_RADIUS / (EARTH_RADIUS + sat_height)
    return np.degrees(np.arctan2(sin_g, cos_g - ratio)).astype(np.float32)


def blend(layers: list[tuple[np.ndarray, np.ndarray]], width: float) -> np.ndarray:
    """Blend RGBA ``layers`` of ``(zenith, rgba)`` into one RGBA array.

    Each pixel comes from the satellite that views it most steeply. Where
    another satellite's view angle is within ``width`` degrees of that, the
    two are feathered into each other: ``width`` is the Seam's half-width. A
    satellite with no data at a pixel takes no part there, so its neighbours
    fill the gap.
    """
    best = np.full(layers[0][0].shape, np.inf, dtype=np.float32)
    for zenith, rgba in layers:
        np.minimum(best, np.where(rgba[3] > 0, zenith, np.inf), out=best)
    colour = np.zeros((3, *best.shape), dtype=np.float32)
    opacity = np.zeros(best.shape, dtype=np.float32)
    weight = np.zeros(best.shape, dtype=np.float32)
    for zenith, rgba in layers:
        w = np.clip((best + width - zenith) / width, 0.0, 1.0)
        w = w * w * (3.0 - 2.0 * w)
        w[rgba[3] == 0] = 0.0
        wa = w * rgba[3]
        colour += wa * rgba[:3]
        opacity += wa
        weight += w
    out = np.zeros((4, *best.shape), dtype=np.uint8)
    seen = opacity > 0
    out[:3, seen] = np.rint(colour[:, seen] / opacity[seen])
    out[3, seen] = np.rint(opacity[seen] / weight[seen])
    return out


def join_renderings(
    renders: dict[str, str],
    dest: str,
    slot: str,
    threads: int,
    zoom: int = ZOOM,
) -> None:
    """Join the lossless renders into one lossless Mosaic at ``dest``.

    ``renders`` maps each contributing position to its render. A position
    left out is a missing Disk: the others fill what they can see. Beyond
    ``MAX_VIEW_ZENITH_DEG`` a Rendering is smeared along the limb and is left out.
    """
    import rasterio
    from rasterio.enums import ColorInterp, Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from rasterio.windows import Window

    pixels = pixels_across(zoom)
    res = 2 * HALF_WORLD / pixels
    transform = from_origin(-HALF_WORLD, HALF_WORLD, res, res)
    centres = HALF_WORLD - (np.arange(pixels) + 0.5) * res  # also x, negated
    lon_all = -np.degrees(centres / EARTH_RADIUS)
    lat_all = np.degrees(2 * np.arctan(np.exp(centres / EARTH_RADIUS)) - np.pi / 2)

    orbit = {}
    for position, path in renders.items():
        with rasterio.open(path) as src:
            proj = src.crs.to_dict()
            orbit[position] = (proj["lon_0"], proj["h"])

    local = threading.local()

    def warped() -> dict:
        # GDAL datasets are not shared between threads.
        if not hasattr(local, "vrts"):
            local.vrts = {
                position: WarpedVRT(
                    rasterio.open(path),
                    crs="EPSG:3857",
                    transform=transform,
                    width=pixels,
                    height=pixels,
                    resampling=Resampling.bilinear,
                    src_alpha=4,
                )
                for position, path in renders.items()
            }
        return local.vrts

    def chunk(origin: tuple[int, int]) -> tuple[Window, np.ndarray | None]:
        row, col = origin
        window = Window(col, row, CHUNK, CHUNK)
        lat, lon = lat_all[row : row + CHUNK], lon_all[col : col + CHUNK]
        zeniths = {p: view_zenith(lat, lon, *orbit[p]) for p in renders}
        layers = []
        best = np.full((CHUNK, CHUNK), np.inf, dtype=np.float32)
        # Steepest view first, so that most chunks read one satellite only.
        for position in sorted(renders, key=lambda p: zeniths[p].min()):
            zenith = zeniths[position]
            if zenith.min() >= MAX_VIEW_ZENITH_DEG or (zenith >= best + SEAM_WIDTH_DEG).all():
                continue  # below the limit, or outside every Seam with a better view
            rgba = warped()[position].read(window=window)
            rgba[3][zenith > MAX_VIEW_ZENITH_DEG] = 0
            if rgba[3].any():
                layers.append((zenith, rgba))
                np.minimum(best, np.where(rgba[3] > 0, zenith, np.inf), out=best)
        if not layers:
            return window, None
        return window, layers[0][1] if len(layers) == 1 else blend(layers, SEAM_WIDTH_DEG)

    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    origins = [(r, c) for r in range(0, pixels, CHUNK) for c in range(0, pixels, CHUNK)]
    with rasterio.open(
        dest,
        "w",
        driver="GTiff",
        width=pixels,
        height=pixels,
        count=4,
        dtype="uint8",
        crs="EPSG:3857",
        transform=transform,
        tiled=True,
        blockxsize=TILE,
        blockysize=TILE,
        compress="ZSTD",
        zstd_level=1,
        num_threads=threads,
        bigtiff="YES",
        sparse_ok=True,
    ) as dst:
        dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
        dst.update_tags(GEORING_SLOT=slot, GEORING_DISKS=",".join(renders))
        with ThreadPoolExecutor(threads) as pool:
            for window, rgba in pool.map(chunk, origins):
                if rgba is not None:
                    dst.write(rgba, window=window)


def encode_mosaic(source: str, dest: str, threads: int, zoom: int = ZOOM) -> None:
    """Write the joined Mosaic as the published COG, in WebP, and check its tile layout."""
    import rasterio
    from rasterio.shutil import copy

    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    # NUM_THREADS covers the encoding; GDAL_NUM_THREADS also unpacks the
    # source on several threads. GDAL's cache size is left to the environment
    # (georing.step): rasterio.Env(GDAL_CACHEMAX=...) counts in bytes.
    with rasterio.Env(GDAL_NUM_THREADS=threads):
        copy(
            source,
            dest,
            driver="COG",
            COMPRESS="WEBP",
            QUALITY=QUALITY,
            BLOCKSIZE=512,
            OVERVIEW_RESAMPLING="AVERAGE",
            NUM_THREADS=threads,
            TILING_SCHEME="GoogleMapsCompatible",
            # GDAL counts zoom in tiles of BLOCKSIZE: 512 px tiles are one level down.
            ZOOM_LEVEL=zoom - 1,
            # The source is already on the grid, so nothing is resampled here.
            WARP_RESAMPLING="NEAREST",
            SPARSE_OK="TRUE",
            # Classic TIFF halves the tile index a client reads first, and a
            # Mosaic is far below its 4 GB limit.
            BIGTIFF="NO",
        )
    check_tile_grid(dest)


def check_tile_grid(path: str) -> None:
    """Check that every level's internal tiles are web map tiles.

    Level ``k`` must be a square of ``512 * 2**z`` pixels that starts at the
    grid's corner and spans the whole world in 512 px blocks. Then its block
    ``(x, y)`` is exactly web tile ``z/x/y``. Raises if any level is not.
    """
    import rasterio

    levels = []
    with rasterio.open(path) as full:
        factors = [1, *full.overviews(1)]
    for k, factor in enumerate(factors):
        options = {"OVERVIEW_LEVEL": k - 1} if k else {}
        with rasterio.open(path, **options) as ds:
            zoom = np.log2(ds.width / TILE)
            t = ds.transform
            aligned = (
                ds.width == ds.height
                and zoom == int(zoom)
                and set(ds.block_shapes) == {(TILE, TILE)}
                and abs(t.c + HALF_WORLD) < 1e-6 * t.a
                and abs(t.f - HALF_WORLD) < 1e-6 * t.a
                and abs(t.a * ds.width - 2 * HALF_WORLD) < 1e-6 * t.a
                and abs(t.e + t.a) < 1e-9
            )
            levels.append(
                {"factor": factor, "pixels": ds.width, "tile_zoom": float(zoom), "aligned": bool(aligned)}
            )
    if not all(level["aligned"] for level in levels) or levels[-1]["pixels"] != TILE:
        raise RuntimeError(f"{path}: tiles are not aligned to the web tile grid: {levels}")

