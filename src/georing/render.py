"""Turn one Disk into a Rendering."""

from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

RECIPE = "georing"  # the satpy composite under src/georing/satpy
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
    native = scn.resample(scn.finest_area(), resampler="native")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    native.save_dataset(
        RECIPE,
        filename=dest,
        writer="geotiff",
        compress="ZSTD",
        zstd_level=1,
        blockxsize=512,
        blockysize=512,
        bigtiff="YES",
        num_threads=threads,
    )


def load_recipe(position: str, disk_dir: str, grid_dir: str, recipe: str = RECIPE):
    """Open the Disk in ``disk_dir`` and make ``recipe`` up to the last resample.

    Returns a satpy Scene whose day layer is still at each band's own
    resolution and whose night layer is finished. Resampling it to its finest
    grid with the ``native`` resampler makes the Recipe itself.
    """
    import hdf5plugin  # noqa: F401  (FCI files are compressed with its filters)
    from satpy import Scene

    from georing.satellites import by_position

    sat = by_position(position)
    files = sorted(
        str(p) for p in Path(disk_dir).iterdir() if not p.name.startswith(".") and p.suffix != ".part"
    )
    _serialise_netcdf_reads()
    quiet_known_warnings()

    scn = Scene(filenames=files, reader=sat.reader)
    scn.load([recipe])
    # satpy has now made what it can without resampling. The night layer is
    # stuck on its two static images, which sit on their own lat/lon grids
    # (satpy issue #2733). Put them on the infrared grid and finish the night
    # layer there, at 1 or 2 km, before anything is brought up to 0.5 km: the
    # cloud compositors build whole-Disk arrays in memory.
    # A Scene iterates over its datasets, not their keys.
    static = [k for k in scn.keys() if scn[k].attrs["area"].crs.is_geographic]  # noqa: SIM118
    like = max(
        (d for d in scn.values() if not d.attrs["area"].crs.is_geographic),
        key=lambda d: d.attrs["area"].pixel_size_x,
    )
    for ds_id in static:
        scn[ds_id] = static_on_grid(scn[ds_id], like.attrs["area"], like, Path(grid_dir) / position)
    scn.generate_possible_composites(unload=True)
    return scn


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


def static_on_grid(image, area, like, cache_dir: Path):
    """Return one of the Recipe's static images on a satellite's grid.

    A satellite's grid does not change between Slots, so the image is warped
    once and kept in ``cache_dir``. It is read back in the chunks of ``like``,
    a band already on the grid: satpy's own resamplers return other chunks,
    and joining the two holds the whole Disk in memory.
    """
    import numpy as np
    import rasterio
    import rioxarray
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    height, width = area.shape
    transform = from_bounds(*area.area_extent, width, height)
    path = cache_dir / f"{image.attrs['name'].strip('_')}.tif"

    def current() -> bool:
        if not path.exists():
            return False
        with rasterio.open(path) as ds:
            return ds.shape == area.shape and ds.transform.almost_equals(transform) and ds.crs == area.crs

    if not current():
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
            dst_transform=transform,
            dst_crs=area.crs,
            # The land mask holds classes, which must not be averaged.
            resampling=Resampling.bilinear if pixels.shape[0] > 2 else Resampling.nearest,
            num_threads=os.cpu_count(),
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        with rasterio.open(
            part, "w", driver="GTiff", width=width, height=height, count=warped.shape[0],
            dtype=warped.dtype, crs=area.crs, transform=transform, tiled=True,
            blockxsize=512, blockysize=512, compress="ZSTD", zstd_level=1,
        ) as dst:
            dst.write(warped)
        part.rename(path)

    grid = rioxarray.open_rasterio(path, chunks={"y": like.chunks[-2], "x": like.chunks[-1]})
    out = grid[:-1].where(grid[-1] > 0).rename(band="bands")
    out = out.drop_vars(["spatial_ref", "x", "y"], errors="ignore").assign_coords(bands=image["bands"].values)
    out.attrs = {**image.attrs, "area": area}
    return out
