import dask.array as da
import numpy as np
import xarray as xr
from trollimage.xrimage import XRImage

from georing.recipe import (
    channel_curves,
    uniform_luminance,
)


def image(pixels: list[list[float]], bands: str = "RGB") -> XRImage:
    """Build an image of one row whose pixels are given as channel tuples on 0 to 255."""
    data = np.array(pixels, dtype=np.float32).T[:, None, :] / 255
    return XRImage(xr.DataArray(da.from_array(data, chunks=(1, 1, 2)), dims=("bands", "y", "x"),
                                coords={"bands": list(bands)}))


def levels(data: xr.DataArray) -> list[list[int]]:
    return np.rint(data.values[:, 0, :].T * 255).astype(int).tolist()


def test_each_channel_follows_its_own_curve():
    out = channel_curves(image([[100, 100, 100], [50, 50, 50]]), xp=[0, 100, 255],
                         red=[0, 110, 255], green=[0, 120, 255], blue=[0, 130, 255])
    assert levels(out) == [[110, 120, 130], [55, 60, 65]]


def test_curves_leave_alpha_and_missing_pixels_alone():
    img = image([[100, 100, 100, 77], [np.nan, np.nan, np.nan, 0]], bands="RGBA")
    out = channel_curves(img, xp=[0, 255], red=[0, 127.5], green=[0, 255], blue=[0, 255])
    assert levels(out.sel(bands=["R", "A"]).isel(x=[0])) == [[50, 77]]
    assert np.isnan(out.sel(bands="R").values[0, 1])


def test_uniform_luminance_keeps_alpha_and_missing_pixels():
    img = image([[30, 128], [200, 51], [np.nan, 0]], bands="LA")
    out = uniform_luminance(img, level=255)
    assert levels(out.isel(x=[0, 1])) == [[255, 128], [255, 51]]
    assert np.isnan(out.sel(bands="L").values[0, 2])


def test_only_the_coldest_cloud_tops_are_opaque_so_storms_keep_their_shading():
    from pathlib import Path

    import yaml
    from pyresample.geometry import AreaDefinition
    from satpy.composites.mask import HighCloudCompositor

    config = Path(__file__).parents[1] / "src/georing/satpy/composites/visir.yaml"
    text = config.read_text().replace("!!python/name:", "")
    layer = yaml.safe_load(text)["composites"]["georing_high_clouds"]
    kwargs = {k: layer[k] for k in ("transition_min_limits", "transition_max", "transition_gamma")}
    area = AreaDefinition("equator", "", "", "EPSG:4326", 4, 1, (0, -0.5, 4, 0.5))
    bt = xr.DataArray(da.from_array(np.array([[300.0, 250.0, 200.0, 175.0]]), chunks=(1, 4)), dims=("y", "x"),
                      coords={"y": [0.0], "x": [0.5, 1.5, 2.5, 3.5]},
                      attrs={"area": area})
    alpha = HighCloudCompositor("high", **kwargs)([bt]).sel(bands="A").values[0]
    assert alpha[0] == 0 and alpha[-1] == 1
    # Tops at 200 K, a deep storm's, are still partly see-through.
    assert 0.5 < alpha[2] < 1


def test_a_colour_table_is_read_between_its_bins_and_held_at_its_ends():
    from georing.recipe import colour_from_table

    centres = np.array([[0.0, 10.0]] * 3)
    # Red follows the first band, green the second; blue is 5 everywhere.
    table = np.zeros((3, 2, 2, 2))
    table[0, 1], table[1, :, 1], table[2] = 10, 10, 5
    bands = np.array([[[2.5, 30, np.nan]], [[7.5, 5, 1]], [[0, 0, 1]]], dtype=np.float32)
    out = colour_from_table(bands, centres, table)
    np.testing.assert_allclose(out[:, 0, :2], [[2.5, 10], [7.5, 5], [5, 5]], atol=1e-5)
    assert np.isnan(out[:, 0, 2]).all()  # missing in one band, missing in all


def test_the_seviri_table_is_whole_and_makes_bright_cloud_white():
    from pathlib import Path

    from georing.recipe import colour_from_table

    with np.load(Path(__file__).parents[1] / "src/georing/satpy/seviri_colour.npz") as f:
        centres, table = f["centres"], f["table"]
    assert centres.shape == (3, table.shape[1]) and np.isfinite(table).all()
    cloud = colour_from_table(np.array([[[85.0]], [[85.0]], [[40.0]]]), centres, table)[:, 0, 0]
    assert np.ptp(cloud) < 0.1 * cloud.mean()


def test_twilight_keeps_the_day_layer_until_the_haze_is_stretched_out():
    from georing.recipe import twilight

    day, night = np.array([0.5, 0.5, 0.5]), np.array([0.2, 0.2, 0.2])
    sunz = np.array([70.0, 76.5, 77.0, 80.0])
    out = twilight(day.repeat(4)[:4], night.repeat(4)[:4], sunz, weight=np.ones(4), gain=1.4, offset=51, start=76, end=78)
    # Untouched before 76 degrees, then in on a smooth step: 0.156 of the way
    # at a quarter, half at 77, fully from 78 on, so no edge shows.
    np.testing.assert_allclose(out, [0.5, 0.5 * (1 + 0.4 * 0.15625) - 0.2 * 0.15625, 0.5 * 1.2 - 0.1, 0.5 * 1.4 - 0.2])


def test_twilight_mixes_the_layers_as_light():
    from georing.recipe import twilight

    out = twilight(np.array([1.0]), np.array([0.0]), np.array([84.0]), weight=np.array([0.5]),
                   gain=1.0, offset=0.0, start=76, end=78)
    # Half the light of white is brighter than half the display value.
    np.testing.assert_allclose(out, [0.5 ** (1 / 2.2)])
    night = twilight(np.array([1.0]), np.array([0.3]), np.array([90.0]), weight=np.array([0.0]),
                     gain=1.4, offset=51, start=76, end=78)
    np.testing.assert_allclose(night, [0.3])


def test_the_twilight_compositor_stretches_and_blends_by_sun_zenith(monkeypatch):
    from pyresample.geometry import AreaDefinition
    from satpy.composites import fill

    from georing.recipe import TwilightCompositor

    monkeypatch.setattr(fill, "enhance2dataset", lambda data, *a, **k: data)  # layers come in enhanced
    area = AreaDefinition("row", "", "", "EPSG:4326", 3, 1, (0, -0.5, 3, 0.5))

    def layer(values):
        data = np.array(values, dtype=np.float64).T[:, None, :]
        return xr.DataArray(da.from_array(data, chunks=(3, 1, 3)), dims=("bands", "y", "x"),
                            coords={"bands": list("RGB")}, attrs={"area": area})

    sunz = xr.DataArray(np.array([[70.0, 80.0, 90.0]]), dims=("y", "x"), attrs={"area": area})
    comp = TwilightCompositor("georing", lim_low=82, lim_high=86, gain=(1.0, 1.0, 1.2), offset=(0, 0, 51))
    out = comp([layer([[0.5] * 3] * 3), layer([[0.1] * 3] * 3), sunz]).values[:, 0, :]
    np.testing.assert_allclose(out[:, 0], [0.5, 0.5, 0.5])  # full day, before the stretch
    np.testing.assert_allclose(out[:, 1], [0.5, 0.5, 0.4], atol=1e-6)  # blue stretched: 0.6 - 0.2
    np.testing.assert_allclose(out[:, 2], [0.1, 0.1, 0.1])  # full night
