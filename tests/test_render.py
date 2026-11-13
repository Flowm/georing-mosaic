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
        coords={"bands": ["R", "G", "B"]}, attrs={"name": "_city_lights", "area": WORLD},
    )


def on_disk_grid(level: int, cache) -> np.ndarray:
    like = xr.DataArray(da.zeros((20, 20), chunks=10), dims=("y", "x"))
    return render.static_on_grid(static_image(level), DISK, like, cache).values


def test_a_static_image_is_warped_onto_a_satellites_grid_once(tmp_path):
    first = on_disk_grid(100, tmp_path)
    assert first.shape == (3, 20, 20)
    assert first[0, 10, 10] == 100            # below the satellite
    assert np.isnan(first[0, 0, 0])           # off the Earth
    # The kept copy answers, whatever is handed in now.
    assert on_disk_grid(200, tmp_path)[0, 10, 10] == 100


def test_only_the_known_lines_of_the_libraries_are_kept_quiet(caplog):
    with warnings.catch_warnings(record=True) as shown:
        warnings.simplefilter("always")
        render.quiet_known_warnings()
        for message, module in [
            ("divide by zero encountered in scalar divide", "trollimage.xrimage"),
            ("invalid value encountered in log", "dask._task_spec"),
            ("invalid value encountered in log10", "dask._task_spec"),
            ("divide by zero encountered in scalar divide", "georing.recipe"),
        ]:
            warnings.warn_explicit(message, RuntimeWarning, "file.py", 1, module=module)
    assert [(str(w.message), w.category) for w in shown] == [
        ("invalid value encountered in log10", RuntimeWarning),
        ("divide by zero encountered in scalar divide", RuntimeWarning),
    ]

    with caplog.at_level(logging.WARNING):
        logging.getLogger("satpy.scene").warning("The following datasets were not created and may require resampling")
        logging.getLogger("satpy.scene").warning("Something else went wrong")
        logging.getLogger("pyspectral.rsr_reader").warning("No sensor name specified in HDF5 file")
    assert caplog.messages == ["Something else went wrong"]
