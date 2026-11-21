"""Join the Renderings of one Slot into a Mosaic on the web tile grid."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
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
# their view angles differ by less than this. Chosen on real Slots; see the plan.
SEAM_WIDTH_DEG = 5.0
# Beyond this view angle a Rendering is smeared along the limb and is left out.
MAX_VIEW_ZENITH_DEG = 85.0
# Over this many degrees short of that limit a Rendering's share fades out, so
# that where a neighbour takes over there is no line.
LIMB_FADE_DEG = 5.0
# Where a satellite looks into the sun's reflection on the sea, its view counts
# as this many degrees more slanted when the Seam is drawn: a neighbour that
# sees the place without glint takes it, and no glint patch is cut off at a
# Seam. Full within the first glint angle, none beyond the second; see the plan.
GLINT_PENALTY_DEG = 20.0
GLINT_ANGLE_DEG = (30.0, 45.0)
# Where glint moved the Seam it lies in the glint, and a 5-degree feather drew
# an edge across it. There a neighbour without glint feathers into the glinting
# view over this many more degrees per degree of penalty, and a view at the
# full penalty keeps this much of its weight: the glint fades out instead.
GLINT_FEATHER = 1.0
GLINT_WEIGHT = 0.2
# WebP quality of the published Mosaic (ADR 0004).
QUALITY = 90
CHUNK = 2048


def pixels_across(zoom: int) -> int:
    """Return the width in pixels of a whole-world image at web zoom level ``zoom``."""
    return 256 << zoom


def view_zenith(
    lat: np.ndarray, lon: np.ndarray, sat_lon: float, sat_height: float, sat_lat: float = 0.0
) -> np.ndarray:
    """Return the angle from vertical, in degrees, at which a satellite is seen.

    ``lat`` is a column and ``lon`` a row, both in degrees; the result is
    their grid. 90 and above means the satellite is below the horizon. The
    satellite is at ``sat_lat``, ``sat_lon`` and ``sat_height`` metres up: an
    inclined orbit, as Meteosat-9's, takes it several degrees off the
    equator. The Earth is taken as a sphere, which shifts every satellite
    alike.
    """
    lat_r, sat_r = np.radians(lat)[:, None], np.radians(sat_lat)
    cos_g = (np.sin(lat_r) * np.sin(sat_r)
             + np.cos(lat_r) * np.cos(sat_r) * np.cos(np.radians(lon - sat_lon))[None, :])
    sin_g = np.sqrt(np.clip(1.0 - cos_g * cos_g, 0.0, None))
    ratio = EARTH_RADIUS / (EARTH_RADIUS + sat_height)
    return np.degrees(np.arctan2(sin_g, cos_g - ratio)).astype(np.float32)


def sun_direction(when: datetime) -> np.ndarray:
    """Return the unit vector toward the sun at ``when``, in Earth-fixed coordinates (x to 0 E, z to the pole)."""
    from pyorbital.astronomy import gmst, sun_ra_dec

    utc = np.datetime64(when.astimezone(UTC).replace(tzinfo=None))
    ra, dec = sun_ra_dec(utc)
    lon = ra - gmst(utc)
    return np.array([np.cos(dec) * np.cos(lon), np.cos(dec) * np.sin(lon), np.sin(dec)])


def glint_penalty(
    lat: np.ndarray, lon: np.ndarray, sun: np.ndarray, sat_lon: float, sat_height: float, sat_lat: float = 0.0
) -> np.ndarray:
    """Return how many degrees a satellite's view counts as more slanted for looking into the sun's reflection.

    ``lat`` is a column and ``lon`` a row, as for `view_zenith`; ``sun`` is
    `sun_direction`. The glint angle is that between the view and the sun's
    mirror image in level ground. The penalty is ``GLINT_PENALTY_DEG``
    within the first of ``GLINT_ANGLE_DEG``, none beyond the second, and
    fades in as the sun rises the first 5 degrees: with the sun below the
    horizon there is no glint.
    """
    lat_r = np.radians(lat, dtype=np.float32)[:, None]
    lon_r = np.radians(lon, dtype=np.float32)[None, :]
    cos_lat, sin_lat, cos_lon, sin_lon = np.cos(lat_r), np.sin(lat_r), np.cos(lon_r), np.sin(lon_r)

    def up_dot(v):  # each pixel's vertical (unit) dotted with v
        x, y, z = (float(c) for c in v)  # numpy scalars would make the result float64
        return cos_lat * (x * cos_lon + y * sin_lon) + z * sin_lat

    sat_r, sat_l = np.radians(sat_lat), np.radians(sat_lon)
    sat = (1 + sat_height / EARTH_RADIUS) * np.array(
        [np.cos(sat_r) * np.cos(sat_l), np.cos(sat_r) * np.sin(sat_l), np.sin(sat_r)])
    # The sun's mirror image, 2 (sun . up) up - sun, dotted with the unit view
    # from the ground to the satellite, (sat - up) / |sat - up|; up . up = 1.
    sun_up = up_dot(sun)
    if (sun_up <= 0).all():
        return np.zeros(sun_up.shape, dtype=np.float32)
    sat_up = up_dot(sat)
    cos_glint = (2 * sun_up * sat_up - sun_up - float(sun @ sat)) / np.sqrt(float(sat @ sat) + 1 - 2 * sat_up)
    glint = np.degrees(np.arccos(np.clip(cos_glint, -1.0, 1.0)))
    near = np.clip((GLINT_ANGLE_DEG[1] - glint) / (GLINT_ANGLE_DEG[1] - GLINT_ANGLE_DEG[0]), 0.0, 1.0)
    day = np.clip(sun_up / np.sin(np.radians(5.0)), 0.0, 1.0)
    return (GLINT_PENALTY_DEG * near * day).astype(np.float32)


def blend(layers: list[tuple[np.ndarray, np.ndarray, np.ndarray]], width: float = SEAM_WIDTH_DEG) -> np.ndarray:
    """Blend RGBA ``layers`` of ``(view angle, rgba, rank)`` into one RGBA array.

    ``rank`` is the angle the view counts as when the Seam is drawn: the
    view angle with `glint_penalty` added. Each pixel comes from the
    satellite of the lowest rank. Where another satellite's rank is within
    ``width`` degrees of that, the two are feathered into each other. Where
    the lowest rank carries more glint penalty than another, that one reaches
    ``GLINT_FEATHER`` degrees further per degree of the difference, and each
    view's weight drops toward ``GLINT_WEIGHT`` with its penalty. Each one's
    share also fades out over the last ``LIMB_FADE_DEG`` of its view
    angle before ``MAX_VIEW_ZENITH_DEG``. A satellite with no data at a pixel
    takes no part there, so its neighbours fill the gap; one alone at a
    pixel keeps its colour however small its share.
    """
    best = np.full(layers[0][0].shape, np.inf, dtype=np.float32)
    best_penalty = np.zeros(best.shape, dtype=np.float32)
    for angle, rgba, rank in layers:
        lower = (rgba[3] > 0) & (rank < best)
        best[lower] = rank[lower]
        best_penalty[lower] = (rank - angle)[lower]
    colour = np.zeros((3, *best.shape), dtype=np.float32)
    opacity = np.zeros(best.shape, dtype=np.float32)
    weight = np.zeros(best.shape, dtype=np.float32)
    for angle, rgba, rank in layers:
        penalty = rank - angle
        reach = width + GLINT_FEATHER * np.maximum(best_penalty - penalty, 0.0)
        w = np.clip((best + reach - rank) / reach, 0.0, 1.0)
        w = w * w * (3.0 - 2.0 * w) * np.clip((MAX_VIEW_ZENITH_DEG - angle) / LIMB_FADE_DEG, 1e-3, 1.0)
        w *= 1.0 - (1.0 - GLINT_WEIGHT) * penalty / GLINT_PENALTY_DEG
        w[(rgba[3] == 0) | (angle > MAX_VIEW_ZENITH_DEG)] = 0.0
        wa = w * rgba[3]
        colour += wa * rgba[:3]
        opacity += wa
        weight += w
    out = np.zeros((4, *best.shape), dtype=np.uint8)
    seen = opacity > 0
    out[:3, seen] = np.rint(colour[:, seen] / opacity[seen])
    out[3, seen] = np.rint(opacity[seen] / weight[seen])
    return out


# The tags a Rendering carries the satellite's actual position in (georing.render).
POSITION_TAGS = ("GEORING_SATELLITE_LON", "GEORING_SATELLITE_HEIGHT", "GEORING_SATELLITE_LAT")


def satellite_positions(path: str) -> list[tuple[float, float, float]]:
    """Return the positions a Rendering's view angles are worked out from: (longitude, height, latitude).

    The first is the Rendering's own grid, which places the satellite on the
    equator at its nominal longitude; the second, if the render step wrote
    it in the tags, where the satellite actually was. The join takes the
    larger view angle of the two. With an inclined orbit (Meteosat-9) the
    satellite saw the far side of its grid more slantwise than the grid
    says, and the near side less, but the grid holds nothing beyond its own
    limb there.
    """
    import rasterio

    with rasterio.open(path) as src:
        tags = src.tags()
        proj = src.crs.to_dict()
    positions = [(proj["lon_0"], proj["h"], 0.0)]
    if all(tag in tags for tag in POSITION_TAGS):
        positions.append(tuple(float(tags[tag]) for tag in POSITION_TAGS))
    return positions


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
    Each pixel comes from the satellite that sees it most steeply, unless it
    looks into the sun's reflection there at ``slot`` (``blend``).
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

    orbits = {position: satellite_positions(path) for position, path in renders.items()}
    sun = sun_direction(datetime.fromisoformat(slot))

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
        zeniths = {p: np.maximum.reduce([view_zenith(lat, lon, *o) for o in orbits[p]]) for p in renders}
        layers = []
        best = np.full((CHUNK, CHUNK), np.inf, dtype=np.float32)
        seen = [p for p in renders if zeniths[p].min() < MAX_VIEW_ZENITH_DEG]
        if not seen:
            return window, None
        if len(seen) == 1:
            penalties = {seen[0]: np.float32(0.0)}
        else:
            penalties = {p: glint_penalty(lat, lon, sun, *orbits[p][-1]) for p in seen}
        # How far a Seam reaches here at most (blend).
        reach = SEAM_WIDTH_DEG + GLINT_FEATHER * np.maximum.reduce(list(penalties.values()))
        # Steepest view first, so that most chunks read one satellite only.
        for position in sorted(seen, key=lambda p: zeniths[p].min()):
            zenith = zeniths[position]
            rank = zenith + penalties[position]
            if (rank >= best + reach).all():
                continue  # outside every Seam with a lower rank
            rgba = warped()[position].read(window=window)
            rgba[3][zenith > MAX_VIEW_ZENITH_DEG] = 0
            if rgba[3].any():
                layers.append((zenith, rgba, rank))
                np.minimum(best, np.where(rgba[3] > 0, rank, np.inf), out=best)
        if not layers:
            return window, None
        return window, layers[0][1] if len(layers) == 1 else blend(layers)

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

