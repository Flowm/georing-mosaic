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
    from satpy.modifiers import angles

    from georing.recipe import TwilightCompositor

    monkeypatch.setattr(fill, "enhance2dataset", lambda data, *a, **k: data)  # layers come in enhanced
    area = AreaDefinition("row", "", "", "EPSG:4326", 5, 1, (0, -0.5, 5, 0.5))

    def grid(values):
        return xr.DataArray(da.from_array(np.array([values], dtype=np.float64)), dims=("y", "x"), attrs={"area": area})

    def layer(values):
        data = np.array(values, dtype=np.float64).T[:, None, :]
        return xr.DataArray(da.from_array(data, chunks=(3, 1, 5)), dims=("bands", "y", "x"),
                            coords={"bands": list("RGB")}, attrs={"area": area})

    sunz = grid([70.0, 80.0, 90.0, 70.0, 70.0])
    # The last two pixels look straight into the sun's reflection.
    sun_azimuth, sat_azimuth = grid([0.0, 0.0, 0.0, 90.0, 90.0]), grid([0.0, 0.0, 0.0, 270.0, 270.0])
    monkeypatch.setattr(angles, "get_angles", lambda data: (sat_azimuth, grid([70.0] * 5), sun_azimuth, sunz))
    monkeypatch.setattr(angles, "get_cos_sza", lambda data: np.cos(np.radians(sunz)))
    orbit = {"satellite_actual_latitude": -6.5, "satellite_actual_longitude": 46.1, "satellite_actual_altitude": 3.6e7}
    comp = TwilightCompositor("georing", lim_low=82, lim_high=86, gain=(1.0, 1.0, 1.2), offset=(0, 0, 51),
                              stretch_start=76, stretch_end=78, glare_sun=(60, 65), glare_angle=(20, 40),
                              burnt=(0.88, 0.98))
    day = layer([[0.5] * 3] * 3 + [[1.0] * 3, [0.5] * 3])
    day.attrs["orbital_parameters"] = orbit
    sea = grid([0.0] * 5)
    result = comp([day, layer([[0.1] * 3] * 5)], optional_datasets=[sea])
    # Where the satellite was survives the night layer's static images, which have no orbit.
    assert result.attrs["orbital_parameters"] == orbit
    out = result.values[:, 0, :]
    np.testing.assert_allclose(out[:, 0], [0.5, 0.5, 0.5])  # full day, before the stretch
    np.testing.assert_allclose(out[:, 1], [0.5, 0.5, 0.4], atol=1e-6)  # blue stretched: 0.6 - 0.2
    np.testing.assert_allclose(out[:, 2], [0.1, 0.1, 0.1])  # full night
    np.testing.assert_allclose(out[:, 3], [0.1, 0.1, 0.1])  # glare burns the sea out: the night layer comes in
    np.testing.assert_allclose(out[:, 4], [0.5, 0.5, 0.5])  # the same glare, not burnt out: day stays
    land = comp([day, layer([[0.1] * 3] * 5)], optional_datasets=[grid([100.0] * 5)])
    np.testing.assert_allclose(land.values[:, 0, 3], [1.0, 1.0, 1.0])  # land keeps the day layer


def test_a_colour_the_table_cannot_vouch_for_fades_to_grey():
    from georing.recipe import distrust, toward_grey

    sunz = np.array([60.0, 85.0, 95.0, 40.0, 40.0])
    satz = np.array([30.0, 30.0, 30.0, 70.0, 30.0])
    brightest = np.array([80.0, 80.0, 80.0, 80.0, 120.0])
    fade = distrust(sunz, satz, brightest, sun=(80, 90), view=(65, 75), reach=(110, 130))
    # Within the table's sun, view and reach; sun halfway past; sun beyond;
    # view halfway past; the brightest band halfway past the table's end.
    np.testing.assert_allclose(fade, [0, 0.5, 1, 0.5, 0.5])
    orange, grey = np.array([36.0, 15.0, 0.0]), np.array([60.0, 60.0, 60.0])
    np.testing.assert_allclose(toward_grey(orange, grey, 0.5), (orange + grey) / 2)


def test_the_grey_is_divided_by_a_sun_no_lower_than_its_cap():
    from georing.recipe import capped_sun_correction

    out = capped_sun_correction(np.array([25.0, 25.0]), np.array([60.0, 80.0]), 70.0)
    np.testing.assert_allclose(out, [50.0, 25.0 / np.cos(np.radians(70.0))])


def test_the_glint_angle_is_zero_looking_into_the_suns_reflection():
    from georing.recipe import glint_angle

    out = glint_angle(np.array([60.0, 60.0, 0.0]), np.array([60.0, 60.0, 0.0]),
                      np.array([90.0, 90.0, 0.0]), np.array([270.0, 90.0, 0.0]))
    # Sun in the east, satellite as low in the west; on the same side; both overhead.
    np.testing.assert_allclose(out, [0.0, 120.0, 0.0], atol=1e-4)


def test_near_the_suns_reflection_is_one_within_the_angle_and_none_beyond():
    from georing.recipe import near_glint

    out = near_glint(np.array([5.0, 15.0, 20.0, 25.0, 40.0]), (15, 25))
    np.testing.assert_allclose(out, [1.0, 1.0, 0.5, 0.0, 0.0])


def test_a_low_sun_glares_where_the_view_is_near_its_reflection():
    from georing.recipe import glare

    out = glare(np.array([60.0, 70.0, 80.0, 80.0, 80.0]), np.array([10.0, 10.0, 10.0, 30.0, 50.0]),
                sun=(65, 75), angle=(20, 40))
    # A high sun; halfway down; low; low but further off; low and far off.
    np.testing.assert_allclose(out, [0.0, 0.5, 1.0, 0.5, 0.0])
