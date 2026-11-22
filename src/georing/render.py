"""Turn one Disk into a Rendering."""

from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

RECIPE = "georing"  # the satpy composite under src/georing/satpy
# The land mask the Recipe reads (visir.yaml); the city lights take Antarctica from it.
LAND_MASK = "gshhs_land_water_mask_3km_i.tif"
# What satpy and its libraries say on every render. Each was traced to a
# cause that leaves the image as it is (the notes, under "satpy"), so it is
# not shown. Anything else they say still is.
KNOWN_WARNINGS = (
    # (start of the message, module it is raised in)
    ("divide by zero encountered in scalar divide", "trollimage"),
    ("invalid value encountered in scalar multiply", "trollimage"),
    ("invalid value encountered in log$", "dask"),
    ("The specified chunks separate the stored chunks", "satpy"),
)
KNOWN_LOG_LINES = {
    "satpy.scene": "The following datasets were not created and may require resampling",
    "pyspectral.rsr_reader": "No sensor name specified in HDF5 file",
    "satpy.readers.generic_image": "cannot convert float NaN to integer",
}


def render_disk(position: str, disk_dir: str, grid_dir: str, dest: str, threads: int) -> None:
    """Render the Disk in ``disk_dir`` to ``dest``, lossless, in the satellite's own view.

    The Mosaic is joined from these files, so it is compressed once.
    """
    scn = load_recipe(position, disk_dir, grid_dir)
    position_tags = satellite_position_tags(scn)
    native = scn.resample(scn.finest_area(), resampler="native")
    position_tags = position_tags or satellite_position_tags(native)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    native.save_dataset(
        RECIPE,
        filename=dest,
        writer="geotiff",
        tags=position_tags,
        compress="ZSTD",
        zstd_level=1,
        blockxsize=512,
        blockysize=512,
        bigtiff="YES",
        num_threads=threads,
    )


def satellite_position_tags(scn) -> dict[str, str]:
    """Return where the satellite actually was during the scan, as the Rendering's tags.

    The bands' grid places the satellite on the equator at its nominal
    longitude; Meteosat-9's inclined orbit takes it several degrees off. The
    Mosaic works out view angles from these tags (georing.mosaic). Empty if
    no band says.
    """
    from georing.mosaic import POSITION_TAGS

    for dataset in scn.values():
        orbit = dataset.attrs.get("orbital_parameters") or {}
        values = [orbit.get(f"satellite_actual_{k}") for k in ("longitude", "altitude", "latitude")]
        if all(v is not None for v in values):
            return {tag: f"{float(v):.4f}" for tag, v in zip(POSITION_TAGS, values, strict=True)}
    return {}


def open_disk(position: str, disk_dir: str):
    """Return the Disk of ``position`` in ``disk_dir`` as a satpy Scene, nothing loaded yet."""
    import hdf5plugin  # noqa: F401  (FCI files are compressed with its filters)
    from satpy import Scene

    from georing.satellites import by_position

    files = sorted(
        str(p) for p in Path(disk_dir).iterdir() if not p.name.startswith(".") and p.suffix != ".part"
    )
    _serialise_netcdf_reads()
    quiet_known_warnings()
    return Scene(filenames=files, reader=by_position(position).reader)


def load_recipe(position: str, disk_dir: str, grid_dir: str, recipe: str = RECIPE):
    """Open the Disk in ``disk_dir`` and make ``recipe`` up to the last resample.

    Returns a satpy Scene whose day layer is still at each band's own
    resolution and whose night layer is finished. Resampling it to its finest
    grid with the ``native`` resampler makes the Recipe itself.
    """
    from georing.lights import layer as lights

    scn = open_disk(position, disk_dir)
    scn.load([recipe])
    # satpy has now made what it can without resampling. The night layer is
    # stuck on its two static images, which sit on their own lat/lon grids
    # (satpy issue #2733). The land mask goes onto the infrared grid, where
    # the cloud layers are made at 1 or 2 km before anything is brought up to
    # 0.5 km: the cloud compositors build whole-Disk arrays in memory. The
    # city lights go onto the finest grid, where the night layer is finished
    # after the last resample, so that towns and roads keep their 500 m.
    # A Scene iterates over its datasets, not their keys.
    static = [k for k in scn.keys() if scn[k].attrs["area"].crs.is_geographic]  # noqa: SIM118
    gridded = sorted(
        (d for d in scn.values() if not d.attrs["area"].crs.is_geographic),
        key=lambda d: d.attrs["area"].pixel_size_x,
    )
    finest, coarsest = gridded[0], gridded[-1]
    cache = Path(grid_dir) / position
    for ds_id in static:
        if lights.is_city_lights(scn[ds_id]):
            chunks = _upsampled_chunks(coarsest, finest)
            scn[ds_id] = lights.on_grid(scn[ds_id], finest.attrs["area"], chunks, cache, _land_mask())
        else:
            scn[ds_id] = static_on_grid(scn[ds_id], coarsest.attrs["area"], coarsest)
    scn.generate_possible_composites(unload=True)
    return scn


def _upsampled_chunks(coarse, fine) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return the chunks ``coarse`` will have once the native resampler brings it to ``fine``'s grid.

    The night layer is finished on the finest grid from the clouds, upsampled
    from the infrared grid, and the city lights. Read in these chunks, the
    lights join the clouds block for block, without a rechunk: in the finest
    band's own chunks a GOES-East render peaked at 14.5 GB, in these at 12.2.
    """
    factor = round(coarse.attrs["area"].pixel_size_x / fine.attrs["area"].pixel_size_x)
    chunks = tuple(tuple(c * factor for c in coarse.chunks[axis]) for axis in (-2, -1))
    if tuple(sum(c) for c in chunks) != fine.attrs["area"].shape:
        return fine.chunks[-2], fine.chunks[-1]
    return chunks


class _Known(logging.Filter):
    """Drops the lines that start with one text."""

    def __init__(self, start: str):
        super().__init__()
        self.start = start

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith(self.start)


_KNOWN_FILTERS = {name: _Known(start) for name, start in KNOWN_LOG_LINES.items()}


def quiet_known_warnings() -> None:
    """Stop the lines in ``KNOWN_WARNINGS`` and ``KNOWN_LOG_LINES`` from being printed."""
    for message, module in KNOWN_WARNINGS:
        warnings.filterwarnings("ignore", message=message, module=module)
    for name, known in _KNOWN_FILTERS.items():
        logging.getLogger(name).addFilter(known)  # a filter already there is not added again


def _serialise_netcdf_reads() -> None:
    """Make satpy read its open NetCDF files one thread at a time.

    The FCI reader keeps its files open and hands their variables to dask
    without a lock. netCDF4 1.7.5 on HDF5 2.2 fails on concurrent reads with
    "NetCDF: HDF error", so this replaces that one method with a locked copy.
    """
    import dask.array as da
    import xarray as xr
    from dask.utils import SerializableLock
    from satpy.readers.core.netcdf import NetCDF4FileHandler

    lock = SerializableLock()

    def _get_var_from_filehandle(self, group, key):
        variable = (self.file_handle if group is None else self.file_handle[group])[key]
        return xr.DataArray(
            da.from_array(variable, lock=lock),
            dims=variable.dimensions,
            attrs=self.accessor.get_object_attrs(variable),
            name=variable.name,
        )

    NetCDF4FileHandler._get_var_from_filehandle = _get_var_from_filehandle


def _land_mask() -> str:
    """Return the land mask the Recipe reads, under satpy's data directory."""
    from satpy import config

    return str(Path(config.get("data_dir")) / "composites" / LAND_MASK)


def static_on_grid(image, area, like):
    """Return one of the Recipe's static images on a satellite's grid.

    It is warped by nearest neighbour, as the land mask holds classes, and
    comes in the chunks of ``like``, a band already on the grid: satpy's own
    resamplers return other chunks, and joining the two holds the whole Disk
    in memory.
    """
    import dask.array as da
    import numpy as np
    import xarray as xr
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    height, width = area.shape
    source = image.attrs["area"]
    pixels = image.values
    # A last band of ones marks what the satellite can see at all.
    pixels = np.concatenate([pixels, np.full_like(pixels[:1], 255)])
    warped = np.zeros((pixels.shape[0], height, width), dtype=pixels.dtype)
    reproject(
        pixels,
        warped,
        src_transform=from_bounds(*source.area_extent, source.width, source.height),
        src_crs=source.crs,
        dst_transform=from_bounds(*area.area_extent, width, height),
        dst_crs=area.crs,
        resampling=Resampling.nearest,
        num_threads=os.cpu_count(),
    )
    grid = da.from_array(warped, chunks=(-1, *like.chunks[-2:]))
    out = xr.DataArray(grid[:-1], dims=("bands", "y", "x"), coords={"bands": image["bands"].values})
    return out.where(grid[-1] > 0).assign_attrs({**image.attrs, "area": area})
