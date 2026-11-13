"""Judge the Recipe against GeoColor on the Comparison scenes.

    georing-compare                      # every scene, with the current Recipe
    georing-compare --set holdout        # only the holdout scenes
    georing-compare day snow --recipe geo_color

For each scene this renders the scene's corner of its Disk and fetches CIRA's
GeoColor of the same scan from SLIDER. Both are in the satellite's own view,
on SLIDER's 1 km pixels, and are written side by side: ours on the left, the
reference on the right.

The scenes come in two sets. The Recipe is fitted to and looked at on the
tuning set; the holdout set, on another day and at other places, only tells
whether a change holds where it was not tuned.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

SLIDER = "https://slider.cira.colostate.edu/data"
# position -> (SLIDER's name for the satellite, its tile size in pixels).
# SLIDER cuts each full disk into 16 by 16 tiles at its finest level, 1 km.
SLIDER_DISKS = {
    "goes-east": ("goes-19", 678),
    "goes-west": ("goes-18", 678),
    "meteosat-0": ("meteosat-12", 696),
    "himawari": ("himawari", 688),
}
TILES_ACROSS = 16


@dataclass(frozen=True)
class ComparisonScene:
    """A fixed place and time at which a Rendering is judged against GeoColor."""

    name: str
    position: str
    slot: datetime
    bbox: tuple[float, float, float, float]  # west, south, east, north in degrees
    shows: str
    set: str = "tuning"  # or "holdout": never fitted to nor tuned by eye


def _slot(day: int, hour: int, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


SETS = ("tuning", "holdout")

COMPARISON_SCENES = (
    # The tuning set.
    ComparisonScene("day", "goes-east", _slot(10, 18), (-90, 15, -75, 30),
                    "Florida, Cuba and the Bahamas: land, shallow water, cumulus"),
    ComparisonScene("night", "goes-east", _slot(10, 6), (-90, 28, -72, 42),
                    "the eastern United States: city lights, low and high cloud"),
    ComparisonScene("terminator", "meteosat-0", _slot(10, 18), (-28, 0, -8, 20),
                    "dusk over West Africa and the Atlantic"),
    ComparisonScene("glint", "goes-west", _slot(10, 18), (-124, -18, -106, 0),
                    "the sun's reflection on the Pacific"),
    ComparisonScene("snow", "himawari", _slot(10, 6), (95, 40, 120, 55),
                    "Mongolia and Lake Baikal in November"),
    ComparisonScene("dust", "meteosat-0", _slot(10, 11), (5, 8, 25, 25),
                    "the Sahara and the Sahel around Lake Chad before noon"),
    ComparisonScene("day-ahi", "himawari", _slot(10, 6), (120, -35, 155, -10),
                    "Australia and the Coral Sea under a high sun"),
    ComparisonScene("day-fci", "meteosat-0", _slot(10, 11), (-15, -20, 15, 5),
                    "the Gulf of Guinea and central Africa under a high sun"),
    ComparisonScene("night-warm", "meteosat-0", _slot(10, 0), (0, 12, 20, 25),
                    "the Sahara and the Sahel at midnight: warm ground"),
    ComparisonScene("dawn", "goes-east", _slot(10, 11), (-80, 8, -58, 26),
                    "dawn over the Caribbean and Venezuela"),
    ComparisonScene("glint-ahi", "himawari", _slot(10, 2), (136, -18, 158, 0),
                    "the sun's reflection around New Guinea"),
    ComparisonScene("storms", "meteosat-0", _slot(10, 0), (12, -8, 28, 4),
                    "thunderstorms over the Congo basin at midnight"),
    ComparisonScene("storms-east", "meteosat-0", _slot(10, 18), (28, -12, 42, 2),
                    "thunderstorms over Tanzania and Lake Victoria by night"),
    # The holdout set: another day, other places.
    ComparisonScene("h-day-ahi", "himawari", _slot(14, 3, 9), (108, -9, 125, 6),
                    "Borneo, Java and Sulawesi before noon", "holdout"),
    ComparisonScene("h-day-fci", "meteosat-0", _slot(14, 12, 9), (-10, 30, 8, 44),
                    "Iberia, Morocco and the western Mediterranean at noon", "holdout"),
    ComparisonScene("h-night-cold", "goes-east", _slot(14, 8, 9), (-66, -40, -56, -28),
                    "the Pampas at the end of winter: cold clear ground", "holdout"),
    ComparisonScene("h-night-warm", "meteosat-0", _slot(14, 1, 9), (18, 25.5, 34, 33),
                    "Libya and Egypt at night: warm desert", "holdout"),
    ComparisonScene("h-dawn", "himawari", _slot(14, 22, 9), (121, 28, 142, 40),
                    "dawn over Korea, Japan and the East China Sea", "holdout"),
    ComparisonScene("h-dusk", "goes-east", _slot(14, 22, 9), (-68, -22, -50, -2),
                    "dusk over Brazil and Bolivia", "holdout"),
    ComparisonScene("h-snow", "goes-east", _slot(14, 15, 9), (-74, -40, -66, -30),
                    "snow on the Andes at the end of winter", "holdout"),
    ComparisonScene("h-glint", "himawari", _slot(14, 22, 9), (162, -4, 179, 12),
                    "the sun's reflection on the central Pacific", "holdout"),
)


@dataclass(frozen=True)
class Window:
    """A scene's rectangle of SLIDER's finest pixel grid of one Disk."""

    crs: object
    left: float  # of the whole Disk, in projection metres
    top: float
    metres: float  # pixel size
    row: int
    col: int
    height: int
    width: int

    @property
    def transform(self):
        from rasterio.transform import from_origin

        return from_origin(
            self.left + self.col * self.metres, self.top - self.row * self.metres, self.metres, self.metres
        )


def window(scene: ComparisonScene, disk_area) -> Window:
    """Return where ``scene`` lies in SLIDER's grid of the Disk with ``disk_area``."""
    from pyproj import Transformer

    # FCI's extent lists its top edge before its bottom one.
    x0, y0, x1, y1 = disk_area.area_extent
    left, right, top = min(x0, x1), max(x0, x1), max(y0, y1)
    # SLIDER's pixels are 1 km, two of the Disk's finest. Where its tiles
    # cover more than the Disk (Himawari: 11008 px for 11000), the Disk sits
    # in their middle.
    metres = (right - left) / (disk_area.width // 2)
    margin = (SLIDER_DISKS[scene.position][1] * TILES_ACROSS - disk_area.width // 2) / 2 * metres
    left, top = left - margin, top + margin
    west, south, east, north = scene.bbox
    lon = np.concatenate([np.linspace(west, east, 50)] * 2 + [np.full(50, west), np.full(50, east)])
    lat = np.concatenate([np.full(50, south), np.full(50, north)] + [np.linspace(south, north, 50)] * 2)
    x, y = Transformer.from_crs("EPSG:4326", disk_area.crs, always_xy=True).transform(lon, lat)
    col, row = int((x.min() - left) / metres), int((top - y.max()) / metres)
    return Window(
        disk_area.crs, left, top, metres, row, col,
        int((top - y.min()) / metres) - row, int((x.max() - left) / metres) - col,
    )


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "georing"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def reference(scene: ComparisonScene, win: Window, cache: Path) -> np.ndarray:
    """Return CIRA's GeoColor of ``scene`` as RGB on ``win``.

    The references are kept in ``cache``: SLIDER holds only some weeks.
    """
    import rasterio
    from rasterio.io import MemoryFile

    path = cache / f"{scene.name}.png"
    if not path.exists():
        name, tile = SLIDER_DISKS[scene.position]
        scans = json.loads(_get(
            f"{SLIDER}/json/{name}/full_disk/geocolor/{scene.slot:%Y%m%d}_by_hour.json"
        ))["timestamps_int"].get(f"{scene.slot:%H}", [])
        # The scan that starts on the hour, as for a Disk.
        first, last = int(f"{scene.slot:%Y%m%d%H%M%S}"), int(f"{scene.slot + timedelta(minutes=1):%Y%m%d%H%M%S}")
        stamps = [s for s in scans if first <= s < last]
        if not stamps:
            raise LookupError(f"SLIDER has no {name} GeoColor for {scene.slot:%Y-%m-%d %H:%M}")
        rows = range(win.row // tile, (win.row + win.height - 1) // tile + 1)
        cols = range(win.col // tile, (win.col + win.width - 1) // tile + 1)

        def fetch(row_col: tuple[int, int]) -> np.ndarray:
            url = (f"{SLIDER}/imagery/{scene.slot:%Y/%m/%d}/{name}---full_disk/geocolor/"
                   f"{stamps[0]}/04/{row_col[0]:03d}_{row_col[1]:03d}.png")
            with MemoryFile(_get(url)) as memory, memory.open() as src:
                return src.read()[:3]

        with ThreadPoolExecutor(8) as pool:
            tiles = list(pool.map(fetch, [(r, c) for r in rows for c in cols]))
        stitched = np.concatenate(
            [np.concatenate(tiles[i * len(cols):(i + 1) * len(cols)], axis=2) for i in range(len(rows))],
            axis=1,
        )
        top, left = win.row - rows[0] * tile, win.col - cols[0] * tile
        cache.mkdir(parents=True, exist_ok=True)
        _write_png(path, stitched[:, top:top + win.height, left:left + win.width])
    with rasterio.open(path) as src:
        return src.read()


def ours(scene: ComparisonScene, recipe: str, work: Path, secrets: dict[str, str]) -> tuple[np.ndarray, Window]:
    """Render ``scene`` with ``recipe``; return it as RGB on SLIDER's grid, and that grid."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    from georing.catalogue import stamp
    from georing.download import download_disk
    from georing.render import load_recipe

    disk_dir = work / "comparison" / "disks" / stamp(scene.slot) / scene.position
    if not (disk_dir / ".complete").exists():
        os.environ.update(secrets)
        download_disk(scene.position, scene.slot.isoformat(), str(disk_dir))
        (disk_dir / ".complete").touch()

    scn = load_recipe(scene.position, str(disk_dir), str(work / "grids"), recipe)
    win = window(scene, scn.finest_area())
    crop = scn.crop(ll_bbox=scene.bbox)
    native = crop.resample(crop.finest_area(), resampler="native")
    tif = Path(os.environ.get("TMPDIR", work / "comparison" / "tmp")) / f"{scene.name}.tif"
    native.save_dataset(recipe, filename=str(tif), writer="geotiff")
    with rasterio.open(tif) as src:
        pixels, transform, crs = src.read()[:3], src.transform, src.crs
    tif.unlink()
    # The Rendering is twice as fine as SLIDER's grid, so average it down.
    out = np.zeros((3, win.height, win.width), dtype=np.uint8)
    reproject(pixels, out, src_transform=transform, src_crs=crs, dst_transform=win.transform,
              dst_crs=crs, resampling=Resampling.average)
    return out, win


def _write_png(path: Path, rgb: np.ndarray) -> None:
    import rasterio

    with rasterio.open(path, "w", driver="PNG", width=rgb.shape[2], height=rgb.shape[1],
                       count=3, dtype="uint8") as dst:
        dst.write(rgb)
    path.with_name(path.name + ".aux.xml").unlink(missing_ok=True)


def difference(mine: np.ndarray, theirs: np.ndarray) -> dict:
    """Summarise how far ``mine`` is from ``theirs``, per channel on a 0 to 255 scale."""
    a, b = mine.reshape(3, -1).astype(np.float32), theirs.reshape(3, -1).astype(np.float32)
    return {
        "ours_mean": [round(float(v), 1) for v in a.mean(axis=1)],
        "reference_mean": [round(float(v), 1) for v in b.mean(axis=1)],
        "mean_abs_difference": [round(float(v), 1) for v in np.abs(a - b).mean(axis=1)],
    }


def worst_channel(figures: dict) -> tuple[str, float]:
    """Return the channel furthest from the reference and its difference."""
    diffs = figures["mean_abs_difference"]
    i = int(np.argmax(diffs))
    return "RGB"[i], diffs[i]


def merge_report(path: Path, report: dict) -> dict:
    """Add ``report`` to the figures kept at ``path`` and return them all.

    A run of some scenes replaces their figures and keeps the others'.
    """
    kept = json.loads(path.read_text()) if path.exists() else {}
    kept.update(report)
    path.write_text(json.dumps(kept, indent=2))
    return kept


def select(names: list[str], set_name: str | None) -> list[ComparisonScene]:
    """Return the Comparison scenes named, or else those of ``set_name``, or else all."""
    if names:
        return [s for s in COMPARISON_SCENES if s.name in names]
    return [s for s in COMPARISON_SCENES if set_name in (None, "all", s.set)]


def main(argv: list[str] | None = None) -> int:
    from georing.render import RECIPE
    from georing.settings import load_dotenv, settings
    from georing.static import fetch_static
    from georing.step import runtime_env

    names = [s.name for s in COMPARISON_SCENES]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenes", nargs="*", help=f"any of: {', '.join(names)}; default: all")
    parser.add_argument("--set", choices=[*SETS, "all"], default="all",
                        help="run only this set of scenes (ignored when scenes are named)")
    parser.add_argument("--recipe", default=RECIPE, help="satpy composite to render")
    parser.add_argument("--work", type=Path, default=Path("work"))
    parser.add_argument("--out", type=Path, help="where the images and figures go; "
                        "default: <work>/comparison/<recipe>")
    parser.add_argument("--cores", type=int, default=8)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    if unknown := set(args.scenes) - set(names):
        parser.error(f"no Comparison scene named {', '.join(sorted(unknown))}")

    work = args.work.resolve()
    out = args.out or work / "comparison" / args.recipe
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[: args.cores])
    # A scratch directory of this run's own, so that runs side by side do
    # not clear each other's files.
    tmp = work / "comparison" / "tmp" / str(os.getpid())
    tmp.mkdir(parents=True, exist_ok=True)
    static = settings().static if settings().static_dir else work / "static"
    fetch_static(str(static))
    os.environ.update(runtime_env(static, args.cores), TMPDIR=str(tmp))
    out.mkdir(parents=True, exist_ok=True)
    secrets = load_dotenv(args.env_file)

    report = {}
    for scene in select(args.scenes, args.set):
        mine, win = ours(scene, args.recipe, work, secrets)
        theirs = reference(scene, win, work / "comparison" / "reference")
        _write_png(out / f"{scene.name}.png", np.concatenate([mine, theirs], axis=2))
        figures = report[scene.name] = {"set": scene.set, **difference(mine, theirs)}
        channel, worst = worst_channel(figures)
        print(f"{scene.name:<13}{scene.set:<8}{scene.position:<11}{scene.slot:%Y-%m-%d %H:%M}  "
              f"ours {figures['ours_mean']}  reference {figures['reference_mean']}  "
              f"|difference| {figures['mean_abs_difference']}  worst {channel} {worst}", flush=True)
    merge_report(out / "difference.json", report)
    print(f"\nSide by side, ours on the left: {out}")
    # Leaving without teardown (see georing.step) also leaves the Himawari
    # segments satpy unpacked, so clear them here.
    shutil.rmtree(tmp, ignore_errors=True)
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
