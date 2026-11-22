import logging
import warnings

import dask.array as da
import numpy as np
import xarray as xr
from pyresample.geometry import AreaDefinition

from georing import render

WORLD = AreaDefinition("world", "", "", "EPSG:4326", 36, 18, (-180, -90, 180, 90))
DISK = AreaDefinition(
    "disk", "", "", {"proj": "geos", "lon_0": 0, "h": 35786023, "a": 6378137, "rf": 298.257, "units": "m"},
    20, 20, (-5.5e6, -5.5e6, 5.5e6, 5.5e6),
)


def static_image(level: int) -> xr.DataArray:
    return xr.DataArray(
        np.full((3, 18, 36), level, dtype=np.uint8), dims=("bands", "y", "x"),
        coords={"bands": ["R", "G", "B"]}, attrs={"name": "_land_water_mask", "area": WORLD},
    )


def test_a_static_image_is_warped_onto_a_satellites_grid_in_its_chunks():
    like = xr.DataArray(da.zeros((20, 20), chunks=10), dims=("y", "x"))
    out = render.static_on_grid(static_image(100), DISK, like)
    assert out.chunks[1:] == like.chunks
    pixels = out.values
    assert pixels.shape == (3, 20, 20)
    assert pixels[0, 10, 10] == 100            # below the satellite
    assert np.isnan(pixels[0, 0, 0])           # off the Earth


def test_only_the_known_lines_of_the_libraries_are_kept_quiet(caplog):
    with warnings.catch_warnings(record=True) as shown:
        warnings.simplefilter("always")
        render.quiet_known_warnings()
        for message, module in [
            ("divide by zero encountered in scalar divide", "trollimage.xrimage"),
            ("invalid value encountered in log", "dask._task_spec"),
            ("invalid value encountered in log10", "dask._task_spec"),
            ("divide by zero encountered in divide", "dask._task_spec"),
            ("Mean of empty slice", "satpy.composites.resolution"),
            ("All-NaN slice encountered", "dask.array.reductions"),
            ("divide by zero encountered in scalar divide", "georing.recipe"),
        ]:
            warnings.warn_explicit(message, RuntimeWarning, "file.py", 1, module=module)
    assert [(str(w.message), w.category) for w in shown] == [
        ("invalid value encountered in log10", RuntimeWarning),
        ("All-NaN slice encountered", RuntimeWarning),
        ("divide by zero encountered in scalar divide", RuntimeWarning),
    ]

    with caplog.at_level(logging.WARNING):
        logging.getLogger("satpy.scene").warning("The following datasets were not created and may require resampling")
        logging.getLogger("satpy.scene").warning("Something else went wrong")
        logging.getLogger("pyspectral.rsr_reader").warning("No sensor name specified in HDF5 file")
        logging.getLogger("pyspectral.rsr_reader").warning("No 'platform_name' in HDF5 file")
    assert caplog.messages == ["Something else went wrong"]



def test_the_lights_are_read_in_the_chunks_the_cloud_layers_will_have():
    class Area:
        def __init__(self, size, shape):
            self.pixel_size_x, self.shape = size, shape

    coarse = xr.DataArray(da.zeros((6, 6), chunks=(4, 3)), dims=("y", "x"), attrs={"area": Area(2000, (6, 6))})
    fine = xr.DataArray(da.zeros((24, 24), chunks=8), dims=("y", "x"), attrs={"area": Area(500, (24, 24))})
    assert render._upsampled_chunks(coarse, fine) == ((16, 8), (12, 12))
    odd = xr.DataArray(da.zeros((25, 24), chunks=8), dims=("y", "x"), attrs={"area": Area(500, (25, 24))})
    assert render._upsampled_chunks(coarse, odd) == odd.chunks


def test_the_sun_is_worked_out_on_the_coarse_grid_and_stands_for_the_fine_pixels_under_it():
    from datetime import datetime

    from satpy.modifiers.angles import get_cos_sza

    fine_area = AreaDefinition("f", "", "", DISK.crs, 40, 40, DISK.area_extent)
    when = datetime(2026, 11, 22, 12)
    coarse = xr.DataArray(da.zeros((20, 20), chunks=10, dtype=np.float32), dims=("y", "x"),
                          attrs={"area": DISK, "start_time": when})
    fine = xr.DataArray(da.zeros((40, 40), chunks=20, dtype=np.float32), dims=("y", "x"),
                        attrs={"area": fine_area, "start_time": when})
    sunz = render.sun_zenith(coarse, fine, ((20, 20), (20, 20)))
    assert sunz.chunks == ((20, 20), (20, 20)) and sunz.dtype == np.float32
    on_coarse = np.degrees(np.arccos(get_cos_sza(coarse).values))
    np.testing.assert_allclose(sunz.compute()[::2, ::2], on_coarse, rtol=1e-5)
    np.testing.assert_array_equal(sunz.compute()[1::2, 1::2], sunz.compute()[::2, ::2])


def test_a_rendering_carries_where_the_satellite_actually_was():
    class Band:
        def __init__(self, attrs):
            self.attrs = attrs

    class Scene:
        def __init__(self, *bands):
            self.bands = bands

        def values(self):
            return self.bands

    sevir = Band({"orbital_parameters": {"satellite_actual_longitude": np.float32(46.123),
                                          "satellite_actual_latitude": -6.476, "satellite_actual_altitude": 35784582.8}})
    tags = render.satellite_position_tags(Scene(Band({}), sevir))
    assert tags == {"GEORING_SATELLITE_LON": "46.1230", "GEORING_SATELLITE_HEIGHT": "35784582.8000",
                    "GEORING_SATELLITE_LAT": "-6.4760"}
    assert render.satellite_position_tags(Scene(Band({"orbital_parameters": {"projection_longitude": -75.0}}))) == {}
