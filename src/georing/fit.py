"""Tabulate Meteosat-9's colour from its neighbours', on what each pair sees at the same time.

    georing-fit-colour \
        --meteosat-0 2026-11-10T07 2026-11-10T09 2026-11-10T11 2026-09-20T09 2026-09-20T11 \
        --himawari 2026-11-10T03 2026-11-10T05 2026-11-10T07 2026-11-10T09 2026-09-20T05 2026-09-20T09 \
        --check 2026-11-10T13 2026-11-19T05

SEVIRI has no blue or green band. For each Slot named this renders, on a
grid of 0.05 degrees over what Meteosat-9 shares with each neighbour, the
neighbour's day colour before its enhancement (red, green and blue as the
Recipe makes them: MTG-I1 to the west, Himawari to the east) and SEVIRI's
three day bands, and keeps the pixels both satellites see well in daylight
and that are even across their neighbours, so that a cloud seen from two
sides does not count. Each neighbour is learnt from on the Slots named
after it. It then cuts SEVIRI's three bands into bins and
writes, per combination of bins, the median colour the neighbours show there
(``TABLE``, beside the Recipe).
Bins with too few pixels take a cubic polynomial of SEVIRI's bands fitted on
all of them, so that the table is whole. ``--check`` Slots are only
measured. The Disks are kept with the Comparison scenes' under
``<work>/comparison/disks``, the pixel pairs under ``<work>/comparison/fit``.
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

# Where both satellites see the ground, at most this far from vertical and with
# the sun at most this far from overhead, the pixel can be learnt from.
MAX_VIEW_DEG = 65.0
MAX_SUN_DEG = 70.0
GRID_DEG = 0.05
SEVIRI_LON = 45.5
SEVIRI_BANDS = (
    ("VIS006", ("georing_sunz", "georing_rayleigh")),
    ("VIS008", ("georing_sunz",)),
    ("IR_016", ("georing_sunz",)),
)
# A pixel whose neighbours differ more than this, in percent reflectance, or
# than this share of its own reflectance where that is more, is an edge (of
# cloud, mostly) and is left out.
MAX_SPREAD = (1.5, 0.1)
# The polynomial weighs pixels so that each step of this many percent of
# SEVIRI's red counts alike: dark sea would otherwise outweigh desert and
# cloud. The figures printed are weighted alike.
WEIGHT_STEP = 2.0
# The table's bins per band, finer toward the dark end (equal steps of the
# square root of the reflectance, 0 to 110%), and the pixels a bin needs for
# its own median.
BINS = 24
TOP = 110.0
MIN_PIXELS = 10
DEGREE = 3
TABLE = Path(__file__).parent / "satpy" / "seviri_colour.npz"
RAYLEIGH = ("georing_sunz", "georing_rayleigh")
CLEAR_LAND = 40.0
# Each neighbour: where it overlaps Meteosat-9 (west, south, east, north), its
# longitude, its red, green and blue before the enhancement, how to load them,
# and whether only land is learnt from it. Himawari sees its overlap 50-65
# degrees off vertical, through more haze than MTG-I1: learnt from, its sea
# turned Meteosat-9's a blotchy grey, and its cloud, blue. Its clear land
# (SEVIRI's brightest band under ``CLEAR_LAND``) brings South Asia's, also
# under the morning sun India is seen in; MTG-I1's sea in the morning, low
# and slantwise over the western Indian Ocean, made the sea blotchy too.
NEIGHBOURS = {
    "meteosat-0": ((-15.0, -55.0, 60.0, 55.0), 0.0,
                   (("vis_06", RAYLEIGH), ("georing_green", None), ("vis_04", RAYLEIGH)), {"resolution": 1000}, False),
    "himawari": ((70.0, -55.0, 125.0, 55.0), 140.7,
                 (("B03", RAYLEIGH), ("georing_green", None), ("B01", RAYLEIGH)), {}, True),
}


def grid(bounds):
    from pyresample.geometry import AreaDefinition

    west, south, east, north = bounds
    width, height = round((east - west) / GRID_DEG), round((north - south) / GRID_DEG)
    return AreaDefinition("fit", "fit", "fit", "EPSG:4326", width, height, bounds)


def _queries(bands):
    from satpy.dataset.dataid import DataQuery

    return [DataQuery(name=n, modifiers=m) if m else DataQuery(name=n) for n, m in bands]


def _on_grid(position: str, slot: datetime, work: Path, bounds, queries, **load) -> np.ndarray:
    """Return the datasets ``queries`` of a Disk averaged onto the common grid."""
    import hdf5plugin  # noqa: F401  (FCI files are compressed with its filters)
    from satpy import Scene

    from georing.compare import comparison_disk
    from georing.render import _serialise_netcdf_reads, quiet_known_warnings
    from georing.satellites import by_position

    _serialise_netcdf_reads()
    quiet_known_warnings()
    disk_dir = comparison_disk(position, slot, work)
    files = sorted(str(p) for p in disk_dir.iterdir() if not p.name.startswith("."))
    scn = Scene(filenames=files, reader=by_position(position).reader)
    scn.load(queries, **load)
    # The whole Scene must outlive the reads: dropping it closes the FCI files.
    out = scn.crop(ll_bbox=bounds).resample(grid(bounds), resampler="bucket_avg")
    return np.stack([out[q].values.astype(np.float32) for q in queries])


def pairs(slot: datetime, work: Path, neighbour: str) -> tuple[np.ndarray, np.ndarray]:
    """Return SEVIRI's bands and ``neighbour``'s colour where both can be learnt from.

    Each is an array of three rows, one per band or channel, in percent.
    """
    from pyorbital.astronomy import sun_zenith_angle

    from georing.mosaic import view_zenith

    bounds, lon_0, colour, load, land_only = NEIGHBOURS[neighbour]
    seviri = _on_grid("meteosat-iodc", slot, work, bounds, _queries(SEVIRI_BANDS))
    theirs = _on_grid(neighbour, slot, work, bounds, _queries(colour), **load)
    lons, lats = grid(bounds).get_lonlats()
    lat, lon = lats[:, 0], lons[0]
    keep = (
        (view_zenith(lat, lon, lon_0, 35786023.0) < MAX_VIEW_DEG)
        & (view_zenith(lat, lon, SEVIRI_LON, 35786023.0) < MAX_VIEW_DEG)
        & (sun_zenith_angle(slot.replace(tzinfo=None), lons, lats) < MAX_SUN_DEG)
        & np.isfinite(seviri).all(axis=0)
        & np.isfinite(theirs).all(axis=0)
        & _even(seviri[0])
        & _even(theirs[0])
    )
    if land_only:
        keep &= (_land(bounds) == 100) & (seviri.max(axis=0) < CLEAR_LAND)
    return seviri[:, keep], theirs[:, keep]


def _land(bounds) -> np.ndarray:
    """Return the Recipe's land mask (0 water, 100 land) on the grid over ``bounds``, as its nearest cells."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    from georing.render import _land_mask

    area = grid(bounds)
    out = np.zeros(area.shape, dtype=np.uint8)
    with rasterio.open(_land_mask()) as src:
        reproject(rasterio.band(src, 1), out, dst_transform=rasterio.transform.from_bounds(*bounds, area.width, area.height),
                  dst_crs="EPSG:4326", resampling=Resampling.nearest)
    return out


def _even(band: np.ndarray) -> np.ndarray:
    """Return where a pixel's 3 by 3 neighbourhood is even, by ``MAX_SPREAD``."""
    from numpy.lib.stride_tricks import sliding_window_view

    spread = np.full(band.shape, np.inf, dtype=np.float32)
    windows = sliding_window_view(band, (3, 3))
    spread[1:-1, 1:-1] = np.nanmax(windows, axis=(-1, -2)) - np.nanmin(windows, axis=(-1, -2))
    absolute, share = MAX_SPREAD
    return spread < np.maximum(absolute, share * band)


def weights(x: np.ndarray) -> np.ndarray:
    """Return a weight per pixel that makes each ``WEIGHT_STEP`` of red count alike."""
    steps = np.floor(x[0] / WEIGHT_STEP).astype(int).clip(0, None)
    counts = np.bincount(steps)
    return 1.0 / counts[steps]


def design(x: np.ndarray) -> np.ndarray:
    """Return, per pixel, every product of SEVIRI's three bands (as fractions) up to ``DEGREE``."""
    powers = sorted(
        (e for e in itertools.product(range(DEGREE + 1), repeat=3) if sum(e) <= DEGREE),
        key=lambda e: (sum(e), [-p for p in e]),
    )
    return np.prod((x / 100)[None, :, :] ** np.array(powers)[:, :, None], axis=1).T


def fit(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fit each row of ``y`` as a polynomial of the rows of ``x``; return the coefficients.

    The fit is made twice: pixels more than three robust deviations off the
    first, such as sun glint, which each satellite sees in another place, are
    left out of the second.
    """
    a = design(x)
    w = np.sqrt(weights(x))[:, None]
    coefficients = []
    for target in y / 100:
        c, *_ = np.linalg.lstsq(a * w, target * w[:, 0], rcond=None)
        residual = a @ c - target
        mad = 1.4826 * np.median(np.abs(residual - np.median(residual)))
        keep = np.abs(residual) < 3 * mad
        c, *_ = np.linalg.lstsq(a[keep] * w[keep], target[keep] * w[keep, 0], rcond=None)
        coefficients.append(c)
    return np.array(coefficients)


def table(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the bins' centres per band and the colour table, as ``ColourTable`` reads them."""
    edges = np.linspace(0, np.sqrt(TOP), BINS + 1) ** 2
    centres = np.tile((edges[1:] + edges[:-1]) / 2, (3, 1))
    coefficients = fit(x, y)
    grid = np.stack(np.meshgrid(*centres, indexing="ij")).reshape(3, -1)
    colour = (design(grid) @ coefficients.T).T * 100
    bins = np.ravel_multi_index(
        [np.clip(np.digitize(band, edges) - 1, 0, BINS - 1) for band in x], (BINS,) * 3
    )
    order = np.argsort(bins)
    bounds = np.searchsorted(bins[order], np.arange(BINS**3 + 1))
    for b in np.nonzero(np.diff(bounds) >= MIN_PIXELS)[0]:
        colour[:, b] = np.median(y[:, order[bounds[b] : bounds[b + 1]]], axis=1)
    return centres.astype(np.float32), colour.reshape(3, BINS, BINS, BINS).clip(0, None).astype(np.float32)


def errors(x: np.ndarray, y: np.ndarray, centres: np.ndarray, colour: np.ndarray) -> list[float]:
    """Return the mean absolute difference per channel, in percent reflectance.

    The mean is weighted so that each brightness counts alike.
    """
    from georing.recipe import colour_from_table

    predicted = colour_from_table(x[:, None, :], centres, colour)[:, 0, :]
    return [round(float(v), 2) for v in np.average(np.abs(predicted - y), axis=1, weights=weights(x))]


def _slot(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(minute=0, second=0, microsecond=0, tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    from georing.lights.cog import lights_path
    from georing.settings import load_dotenv, settings
    from georing.static import fetch_static
    from georing.step import runtime_env

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for neighbour in NEIGHBOURS:
        parser.add_argument(f"--{neighbour}", nargs="*", type=_slot, default=[],
                            help=f"Slots to learn from {neighbour} on, such as 2026-11-10T09")
    parser.add_argument("--check", nargs="*", type=_slot, default=[], help="Slots only measured, on every neighbour")
    parser.add_argument("--work", type=Path, default=Path("work"))
    parser.add_argument("--cores", type=int, default=8)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)

    work = args.work.resolve()
    static = settings().static if settings().static_dir else work / "static"
    fetch_static(str(static))
    os.environ.update(runtime_env(static, args.cores, lights_path(work)), **load_dotenv(args.env_file))

    learnt = {n: getattr(args, n.replace("-", "_")) for n in NEIGHBOURS}
    data = {}
    for neighbour, slots in learnt.items():
        for slot in [*slots, *args.check]:
            land = "-clear-land" if NEIGHBOURS[neighbour][4] else ""
            cache = work / "comparison" / "fit" / f"{slot:%Y%m%dT%H}-{neighbour}{land}.npz"
            if not cache.exists():
                cache.parent.mkdir(parents=True, exist_ok=True)
                np.savez(cache, *pairs(slot, work, neighbour))
            with np.load(cache) as f:
                data[slot, neighbour] = (f["arr_0"], f["arr_1"])
            print(f"{slot:%Y-%m-%d %H:%M} {neighbour}: {data[slot, neighbour][0].shape[1]} pixels", flush=True)

    x = np.concatenate([data[s, n][0] for n, slots in learnt.items() for s in slots], axis=1)
    y = np.concatenate([data[s, n][1] for n, slots in learnt.items() for s in slots], axis=1)
    centres, colour = table(x, y)
    np.savez_compressed(TABLE, centres=centres, table=colour)
    print("\nMean |difference| from the neighbour in percent reflectance (red, green, blue):")
    print(f"  fitted on {x.shape[1]} pixels: {errors(x, y, centres, colour)}")
    for slot in args.check:
        for n in NEIGHBOURS:
            if data[slot, n][0].shape[1]:
                print(f"  {slot:%Y-%m-%d %H:%M} {n} (only measured): {errors(*data[slot, n], centres, colour)}")
    print(f"\nWritten to {TABLE}")
    sys.stdout.flush()
    os._exit(0)  # without teardown, as a step leaves (georing.step)


if __name__ == "__main__":
    raise SystemExit(main())
