import base64
import io
import json

import dask.array as da
import numpy as np
import pytest
import rasterio
import xarray as xr
from pyresample.geometry import AreaDefinition
from trollimage.xrimage import XRImage

from georing.lights import cog as lights
from georing.lights import layer

WORLD = AreaDefinition("world", "", "", "EPSG:4326", 36, 18, (-180, -90, 180, 90))
DISK = AreaDefinition(
    "disk", "", "", {"proj": "geos", "lon_0": 0, "h": 35786023, "a": 6378137, "rf": 298.257, "units": "m"},
    20, 20, (-5.5e6, -5.5e6, 5.5e6, 5.5e6),
)


def levels(data: xr.DataArray) -> list[list[int]]:
    return np.rint(data.values[:, 0, :].T * 255).astype(int).tolist()


def test_a_tile_is_placed_by_its_number_from_180w_and_90n():
    assert lights.tile_transform(0, 0).c == -180 and lights.tile_transform(0, 0).f == 90
    t = lights.tile_transform(35, 17)
    assert (t.c, t.f, t.a) == (170, -80, 1 / 240)


def test_radiance_and_land_survive_the_cog_and_the_top_value_stays_free():
    bands = lights.encode(np.array([0.0, 0.5, 12.34, 1e6]), np.array([True, False, True, False]))
    assert bands.dtype == np.uint16
    radiance, land = lights.decode(bands.astype(float))
    np.testing.assert_allclose(radiance[:3], [0.0, 0.5, 12.3])
    assert bands[0, 3] == 65534  # 65535 marks what a satellite cannot see
    np.testing.assert_array_equal(land, [1, 0, 1, 0])


def test_a_tile_gives_its_radiance_and_land_with_fill_as_zero(tmp_path, monkeypatch):
    import h5py

    monkeypatch.setattr(lights, "TILE_PX", 2)
    path = tmp_path / "VJ146A4.A2025001.h20v04.002.2026000000000.h5"
    with h5py.File(path, "w") as f:
        fields = f.create_group("HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields")
        fields["AllAngle_Composite_Snow_Free"] = np.array([[-999.9, 3.5], [0.0, np.nan]], dtype=np.float32)
        fields["AllAngle_Composite_Snow_Free_Num"] = np.ones((2, 2), dtype=np.uint16)  # a longer name, not this
        fields["Land_Water_Mask"] = np.array([[3, 1], [5, 2]], dtype=np.uint8)
    radiance, land = lights.layers(path)
    np.testing.assert_array_equal(radiance, [[0, 3.5], [0, 0]])
    np.testing.assert_array_equal(land, [[False, True], [True, False]])


def test_the_earthdata_token_is_asked_for_with_the_login(monkeypatch):
    asked = {}

    def urlopen(request, timeout):
        asked.update(url=request.full_url, method=request.get_method(), auth=request.get_header("Authorization"))
        return io.BytesIO(json.dumps({"access_token": "abc", "token_type": "Bearer"}).encode())

    monkeypatch.setattr(lights.urllib.request, "urlopen", urlopen)
    assert lights.earthdata_token("someone", "secret") == "abc"
    assert asked["method"] == "POST" and asked["url"].endswith("/find_or_create_token")
    assert base64.b64decode(asked["auth"].removeprefix("Basic ")) == b"someone:secret"


def test_without_a_login_the_lights_cannot_be_built(tmp_path, monkeypatch):
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    with pytest.raises(lights.NoLogin, match="EARTHDATA_USERNAME"):
        lights.build_city_lights(str(tmp_path / "lights.tif"), {"EARTHDATA_USERNAME": "someone"})
    # A COG that is there needs no login.
    (tmp_path / "there.tif").write_bytes(b"cog")
    assert lights.build_city_lights(str(tmp_path / "there.tif"), {}) == str(tmp_path / "there.tif")


def test_tiles_are_joined_into_a_global_cog_with_open_sea_as_zero(tmp_path, monkeypatch):
    # A world of 10 px tiles, 1 px per degree, stands in for 2400 px tiles.
    monkeypatch.setattr(lights, "TILE_PX", 10)
    monkeypatch.setattr(lights, "PER_DEGREE", 1)
    tile = tmp_path / "h18v04.tif"
    radiance = np.zeros((10, 10), dtype=np.float32)
    radiance[0, 0] = 7.0
    lights.write_tile(radiance, np.ones((10, 10), bool), 18, 4, tile)
    dest = tmp_path / "lights.tif"
    lights.write_cog([tile], dest, threads=1)

    with rasterio.open(dest) as cog:
        assert cog.shape == (180, 360) and cog.count == 2
        assert cog.tags()["product"] == "VJ146A4"
        data = cog.read()
    # Tile h18v04 starts at 0°E, 50°N: column 180, row 40.
    assert data[0, 40, 180] == 70 and data[1, 40, 180] == lights.LAND
    assert data[:, 0, 0].tolist() == [0, 0]
    assert not (tmp_path / "lights.whole.tif").exists()


def test_the_city_lights_are_warped_from_their_file_and_again_when_it_changes(tmp_path):
    import os

    from rasterio.transform import from_bounds

    def write(level):
        path = tmp_path / "lights.tif"
        bands = lights.encode(np.full((18, 36), level), np.ones((18, 36), bool))
        with rasterio.open(path, "w", driver="GTiff", width=36, height=18, count=2, dtype="uint16",
                           crs="EPSG:4326", transform=from_bounds(-180, -90, 180, 90, 36, 18)) as dst:
            dst.write(bands)
        return path

    def grid(path):
        image = xr.DataArray(da.zeros((2, 18, 36)), dims=("bands", "y", "x"), coords={"bands": ["L", "A"]},
                             attrs={"standard_name": "georing_city_lights", "area": WORLD, "filename": str(path)})
        return layer.on_grid(image, DISK, ((10, 10), (10, 10)), tmp_path / "grids").values

    first = grid(write(12.5))
    assert first.shape == (2, 20, 20) and first.dtype == np.float32
    np.testing.assert_allclose(first[:, 10, 10], [12.5, 1.0])   # radiance and land below the satellite
    assert np.isnan(first[:, 0, 0]).all()                        # off the Earth
    path = write(3.0)
    os.utime(path, (1, 1))                                       # a new file, as a new year would be
    np.testing.assert_allclose(grid(path)[0, 10, 10], 3.0)


def test_city_lights_are_coloured_by_radiance_over_land_and_sea():
    # Radiance (L) and share of land (A) come as they are, not on 0 to 255.
    data = np.array([[0.0, 1.0], [9.0, 1.0], [0.0, 0.0], [9.0, 0.0], [np.nan, 1.0]], dtype=np.float32).T[:, None, :]
    img = XRImage(xr.DataArray(da.from_array(data, chunks=(2, 1, 5)), dims=("bands", "y", "x"),
                               coords={"bands": ["L", "A"]}))
    # 9 nW/cm²/sr lies halfway between 0 and 99 on the logarithm of 1 + radiance.
    out = layer.colour_by_radiance(img, xp=[0, 99], red=[40, 240], green=[20, 220], blue=[60, 60], sea=[8, 8, 8])
    assert list(out["bands"].values) == ["R", "G", "B"]
    assert levels(out.isel(x=[0, 1, 2])) == [[40, 20, 60], [140, 120, 60], [8, 8, 8]]
    # A light at sea is raised from the sea's colour as from land's.
    assert levels(out.isel(x=[3])) == [[108, 108, 8]]
    assert np.isnan(out.values[:, 0, 4]).all()


def test_a_tile_is_asked_for_again_after_a_passing_error(tmp_path, monkeypatch):
    import urllib.error

    monkeypatch.setattr(lights, "PAUSE_S", 0)
    # LAADS answers both for tiles it serves a minute later.
    answers = [urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None),
               urllib.error.HTTPError("u", 404, "Not Found", {}, None), None]
    done = []

    def download(entry, h5, token):
        if answer := answers.pop(0):
            raise answer
        done.append(h5)

    monkeypatch.setattr(lights, "_download", download)
    monkeypatch.setattr(lights, "layers", lambda h5: (np.zeros((2, 2)), np.zeros((2, 2), bool)))
    monkeypatch.setattr(lights, "write_tile", lambda *a: None)
    monkeypatch.setattr(lights.Path, "unlink", lambda self: None)
    lights._tile({"name": "VJ146A4.A2025001.h01v02.002.1.h5", "downloadsLink": "u", "size": 1}, tmp_path, "t")
    assert len(done) == 1 and not answers


def test_a_grid_that_runs_south_up_gets_its_lights_the_right_way_round(tmp_path):
    from rasterio.transform import from_bounds

    # Lights only north of the equator.
    radiance = np.zeros((18, 36))
    radiance[:9] = 20.0
    path = tmp_path / "lights.tif"
    with rasterio.open(path, "w", driver="GTiff", width=36, height=18, count=2, dtype="uint16",
                       crs="EPSG:4326", transform=from_bounds(-180, -90, 180, 90, 36, 18)) as dst:
        dst.write(lights.encode(radiance, np.ones((18, 36), bool)))
    south_up = AreaDefinition("fci", "", "", DISK.crs, 20, 20, (-5.5e6, 5.5e6, 5.5e6, -5.5e6))
    image = xr.DataArray(da.zeros((2, 18, 36)), dims=("bands", "y", "x"), coords={"bands": ["L", "A"]},
                         attrs={"standard_name": "georing_city_lights", "area": WORLD, "filename": str(path)})
    grid = layer.on_grid(image, south_up, ((10, 10), (10, 10)), tmp_path / "grids").values
    # The first rows of a south-up grid are the south: dark.
    assert grid[0, 6, 10] == 0 and grid[0, 13, 10] == 20


def test_a_refused_login_is_not_asked_again(tmp_path, monkeypatch):
    import urllib.error

    calls = []

    def download(entry, h5, token):
        calls.append(1)
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(lights, "_download", download)
    with pytest.raises(urllib.error.HTTPError):
        lights._tile({"name": "VJ146A4.A2025001.h01v02.002.1.h5", "downloadsLink": "u", "size": 1}, tmp_path, "t")
    assert len(calls) == 1


def test_south_of_black_marbles_tiles_the_land_comes_from_the_land_mask(tmp_path):
    from rasterio.transform import from_bounds

    # Black Marble's COG holds everything as sea (no tiles); the land mask
    # holds land everywhere.
    lights_path, mask_path = tmp_path / "lights.tif", tmp_path / "mask.tif"
    with rasterio.open(lights_path, "w", driver="GTiff", width=36, height=18, count=2, dtype="uint16",
                       crs="EPSG:4326", transform=from_bounds(-180, -90, 180, 90, 36, 18)) as dst:
        dst.write(lights.encode(np.zeros((18, 36)), np.zeros((18, 36), bool)))
    with rasterio.open(mask_path, "w", driver="GTiff", width=72, height=36, count=1, dtype="uint8", nodata=255,
                       crs="EPSG:4326", transform=from_bounds(-180, -90, 180, 90, 72, 36)) as dst:
        dst.write(np.full((1, 36, 72), 100, dtype=np.uint8))
    image = xr.DataArray(da.zeros((2, 18, 36)), dims=("bands", "y", "x"), coords={"bands": ["L", "A"]},
                         attrs={"standard_name": "georing_city_lights", "area": WORLD, "filename": str(lights_path)})
    grid = layer.on_grid(image, WORLD, ((18,), (36,)), tmp_path / "grids", str(mask_path)).values
    # Rows of 10 degrees from 90N: the last two lie south of 70S.
    np.testing.assert_allclose(grid[1, :16], 0.0)
    np.testing.assert_allclose(grid[1, 16:], 1.0)


def test_the_lights_come_on_after_sunset_the_bright_ones_first():
    radiance = np.array([[100.0, 100.0, 100.0, 2.0]], dtype=np.float32)
    lights = xr.DataArray(
        np.stack([radiance, np.ones_like(radiance)]), dims=("bands", "y", "x"),
        coords={"bands": ["L", "A"]}, attrs={"dusk": (84, 96), "decades": 3, "area": DISK},
    )
    # The sun still up, halfway through dusk, past its end; a dim light halfway.
    sunz = da.from_array(np.array([[80.0, 90.0, 100.0, 90.0]], dtype=np.float32))
    out = layer.after_sunset(lights, sunz)
    np.testing.assert_allclose(out.sel(bands="L").values[0], [0.1, 100 * 10**-1.5, 100.0, 2 * 10**-1.5], rtol=1e-5)
    np.testing.assert_array_equal(out.sel(bands="A").values, 1)
    assert out.dtype == np.float32 and out.attrs["dusk"] == (84, 96)
