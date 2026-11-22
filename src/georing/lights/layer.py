"""The city lights in the Recipe: the COG read, put on a satellite's grid and coloured.

The Recipe names ``CityLights`` and ``colour_by_radiance``; the render hands
the image to ``on_grid``. The COG itself is made by ``georing.lights``.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from satpy.composites.aux_data import StaticImageCompositor

from georing.lights.cog import decode

STANDARD_NAME = "georing_city_lights"
# What the lights hold on a satellite's grid where it cannot see; the COG
# never holds it (``georing.lights.cog.encode``).
OFF_DISK = 65535
# Rows of a satellite's grid warped at once: 45 MB for a 0.5 km Disk.
STRIP_ROWS = 512
# Black Marble has no tiles south of this latitude: the COG holds Antarctica
# beyond it as sea. There the land comes from the Recipe's land mask.
SOUTH_EDGE = -70.0


class CityLights(StaticImageCompositor):
    """The Recipe's compositor for the city lights: satpy's static image, naming its file.

    The COG is too large to hold in memory whole, so ``on_grid`` warps it
    from the file, a window at a time.
    """

    def __call__(self, *args, **kwargs):
        img = super().__call__(*args, **kwargs)
        img.attrs["filename"] = self._retrieve_data_file()
        return img


def is_city_lights(image) -> bool:
    return image.attrs.get("standard_name") == STANDARD_NAME


def on_grid(image, area, chunks, cache_dir: Path, land_mask: str | None = None):
    """Return the city lights on a satellite's grid: radiance as L, the share of land as A.

    The COG is warped onto ``area`` once and kept in ``cache_dir``, and warped
    again when the COG or ``land_mask`` changes. It is read back in
    ``chunks`` (rows, columns), those of what it will be joined with. What
    the satellite cannot see is missing. South of ``SOUTH_EDGE`` the share of
    land comes from ``land_mask`` (0 water, 100 land), if given.
    """
    import rasterio
    import rioxarray
    import xarray as xr
    from rasterio.transform import from_bounds

    height, width = area.shape
    transform = from_bounds(*area.area_extent, width, height)
    path = cache_dir / f"{STANDARD_NAME}.tif"
    source = image.attrs["filename"]
    made_from = f"{source} {os.path.getmtime(source):.0f}"
    if land_mask:
        made_from += f"; land south of {SOUTH_EDGE:g}: {land_mask} {os.path.getmtime(land_mask):.0f}"
    current = False
    if path.exists():
        with rasterio.open(path) as ds:
            current = (ds.shape == area.shape and ds.transform.almost_equals(transform) and ds.crs == area.crs
                       and ds.tags().get("made_from") == made_from)
    if not current:
        _warp(source, path, area, transform, made_from, land_mask)
    grid = rioxarray.open_rasterio(path, chunks={"band": -1, "y": chunks[0], "x": chunks[1]})
    # float32 as the satellite's bands: float64 here made every later step
    # of the night layer and the blend float64, and a render twice the memory.
    out = xr.concat(decode(grid), dim="band").where(grid[0] != OFF_DISK).astype(np.float32).rename(band="bands")
    out = out.drop_vars(["spatial_ref", "x", "y"], errors="ignore").assign_coords(bands=["L", "A"])
    out.attrs = {**image.attrs, "area": area}
    return out


def _warp(source: str, path: Path, area, transform, made_from: str, land_mask: str | None = None) -> None:
    """Warp the COG onto ``area`` and write it to ``path``, a strip of rows at a time.

    The values are averaged: radiance and a share of land average well. Each
    strip reads only the part of the COG under it. A strip wholly off the
    Earth is left as ``OFF_DISK``: GDAL fails on it instead (Meteosat's grid
    reaches past the Earth's edge). GDAL warps onto rows that run north to
    south and columns west to east; a grid that runs the other way, as FCI's
    runs south-up, gets each strip flipped into its place. A strip reaching south of
    ``SOUTH_EDGE`` takes its share of land there from ``land_mask``.
    """
    import rasterio
    from pyproj import Transformer
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject
    from rasterio.windows import Window

    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    height, width = area.shape
    x0, y0, x1, y1 = area.area_extent
    flip_x, flip_y = x0 > x1, y0 > y1
    upright = from_bounds(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), width, height)
    to_lonlat = Transformer.from_crs(area.crs, "EPSG:4326", always_xy=True)
    mask = rasterio.open(land_mask) if land_mask else None
    with rasterio.open(source) as src, rasterio.open(
        part, "w", driver="GTiff", width=width, height=height, count=src.count, dtype=src.dtypes[0],
        crs=area.crs, transform=transform, nodata=OFF_DISK, tiled=True, blockxsize=512, blockysize=512,
        compress="ZSTD", zstd_level=1, bigtiff="IF_SAFER", num_threads="ALL_CPUS",
    ) as dst:
        for row in range(0, height, STRIP_ROWS):
            rows = min(STRIP_ROWS, height - row)
            strip = np.full((src.count, rows, width), OFF_DISK, dtype=src.dtypes[0])
            strip_transform = upright @ upright.translation(0, row)
            # Does any of the strip see the Earth? Sample it on a grid.
            cols, lines = np.meshgrid(np.linspace(0, width, 257), np.linspace(0, rows, 9))
            xs, ys = strip_transform @ (cols, lines)
            lon, lat = to_lonlat.transform(xs, ys)
            if np.isfinite(lon).any():
                reproject(
                    rasterio.band(src, list(range(1, src.count + 1))), strip,
                    dst_transform=strip_transform, dst_crs=area.crs, dst_nodata=OFF_DISK,
                    resampling=Resampling.average, init_dest_nodata=True, num_threads=os.cpu_count(),
                    warp_mem_limit=512,
                )
                # The sample grid is coarse: a strip a degree short of the edge may reach it.
                if mask is not None and np.nanmin(np.where(np.isfinite(lat), lat, np.inf)) < SOUTH_EDGE + 1:
                    _land_from_mask(strip, mask, strip_transform, area.crs, to_lonlat)
            into = height - row - rows if flip_y else row
            dst.write(strip[:, ::-1 if flip_y else 1, ::-1 if flip_x else 1], window=Window(0, into, width, rows))
        dst.update_tags(made_from=made_from)
    if mask is not None:
        mask.close()
    part.rename(path)


def _land_from_mask(strip, mask, strip_transform, crs, to_lonlat) -> None:
    """Set the share of land in ``strip`` south of ``SOUTH_EDGE`` from the land ``mask``, averaged."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    rows, width = strip.shape[1:]
    land = np.full((rows, width), 255, dtype=np.uint8)
    reproject(
        rasterio.band(mask, 1), land, dst_transform=strip_transform, dst_crs=crs, dst_nodata=255,
        resampling=Resampling.average, init_dest_nodata=True, num_threads=os.cpu_count(), warp_mem_limit=512,
    )
    cols, lines = np.meshgrid(np.arange(width) + 0.5, np.arange(rows) + 0.5)
    _, lat = to_lonlat.transform(*(strip_transform @ (cols, lines)))
    south = (lat < SOUTH_EDGE) & (land != 255) & (strip[1] != OFF_DISK)
    strip[1][south] = land[south]


def colour_by_radiance(img, xp, red, green, blue, sea=(0, 0, 0), **kwargs):
    """The Recipe's enhancement for the city lights: colour them by radiance, over land or sea.

    The image holds radiance in nW/cm²/sr as L and the share of land, 0 to
    1, as A (``on_grid``). ``xp`` holds radiances; ``red``, ``green`` and
    ``blue`` the colour over land, on 0 to 255, given to each. Between them
    the colour follows the logarithm of 1 + radiance, as the eye sees
    lights. Unlit land takes the colour at radiance 0 and unlit sea the
    colour ``sea``; a light at sea is raised from it as from land. Missing
    pixels stay missing.
    """
    import dask.array as da
    import xarray as xr

    from georing.recipe import curve

    data = img.data
    level = da.log1p(da.maximum(data.sel(bands="L").data, 0))
    water = 1 - data.sel(bands="A").data
    xp = np.log1p(np.asarray(xp, dtype=float))
    bands = [
        da.map_blocks(curve, level, xp, np.asarray(fp, dtype=float) / 255, dtype=level.dtype)
        - water * ((fp[0] - dark) / 255)
        for fp, dark in zip((red, green, blue), sea, strict=True)
    ]
    img.data = xr.DataArray(
        da.stack(bands), dims=data.dims, attrs=data.attrs,
        coords={**{k: v for k, v in data.coords.items() if k != "bands"}, "bands": ["R", "G", "B"]},
    )
    return img.data
