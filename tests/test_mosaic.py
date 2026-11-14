import numpy as np
import pytest

from georing.mosaic import blend, seam_angle, view_zenith

HEIGHT = 35786023.0
EAST, WEST = -75.2, -137.0


def layer(colour: int, zenith: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.zeros((4, *zenith.shape), dtype=np.uint8)
    rgba[0], rgba[3] = colour, 255
    return zenith, rgba


def test_view_zenith_is_zero_below_the_satellite_and_90_at_the_limb():
    zenith = view_zenith(np.array([0.0]), np.array([EAST, EAST + 81.3]), EAST, HEIGHT)
    assert zenith[0, 0] == pytest.approx(0, abs=1e-3)
    assert zenith[0, 1] == pytest.approx(90, abs=0.1)


def test_the_india_seam_is_viewed_at_about_80_degrees_from_both_sides():
    meteosat = view_zenith(np.array([0.0]), np.array([70.35]), 0.0, HEIGHT)
    himawari = view_zenith(np.array([0.0]), np.array([70.35]), 140.7, HEIGHT)
    assert meteosat[0, 0] == pytest.approx(himawari[0, 0], abs=1e-3)
    assert 78 < meteosat[0, 0] < 85  # inside the default limit


def test_a_coarser_imager_counts_as_a_finer_one_looking_slantwise():
    zenith = np.array([[0.0, 40.0]], dtype=np.float32)
    assert seam_angle(zenith, 1.0) is zenith
    # A 3 km pixel straight down is as large as a 1 km one seen at 70.5 degrees.
    assert seam_angle(zenith, 3.0)[0, 0] == pytest.approx(np.degrees(np.arccos(1 / 3)), abs=1e-3)
    assert seam_angle(zenith, 3.0)[0, 1] > 70.5


def test_blend_takes_the_steeper_view_and_feathers_only_at_the_seam():
    lon = np.array([-110.0, (EAST + WEST) / 2, -102.0])
    lat = np.array([0.0])
    out = blend([
        layer(200, view_zenith(lat, lon, EAST, HEIGHT)),
        layer(100, view_zenith(lat, lon, WEST, HEIGHT)),
    ], widths=[5.0, 5.0])
    assert out[0, 0].tolist() == [100, 150, 200]
    assert out[3, 0].tolist() == [255, 255, 255]


def test_blend_feather_ends_where_the_views_differ_by_the_seam_width():
    near = np.full((1, 1), 30.0, dtype=np.float32)
    out = blend([layer(200, near), layer(100, near + 5.0)], widths=[5.0, 5.0])
    assert out[0, 0, 0] == 200


def test_a_satellite_without_data_leaves_the_pixel_to_its_neighbour():
    steep, shallow = np.full((1, 2), 20.0, np.float32), np.full((1, 2), 60.0, np.float32)
    hole = layer(200, steep)
    hole[1][3, 0, 0] = 0
    out = blend([hole, layer(100, shallow)], widths=[5.0, 5.0])
    assert out[0, 0].tolist() == [100, 200]
    assert out[3, 0].tolist() == [255, 255]


def test_a_pixel_no_satellite_sees_stays_transparent():
    empty = layer(200, np.full((1, 1), 20.0, np.float32))
    empty[1][3] = 0
    assert blend([empty, empty], widths=[5.0, 5.0])[:, 0, 0].tolist() == [0, 0, 0, 0]


# -- the join and encode steps, on two small Disks ---------------------------


def write_render(path, lon_0: float, red: int) -> str:
    """Write a 220 px full-disk render of one colour, as the render step's lossless copy."""
    import rasterio
    from rasterio.transform import from_origin

    crs = {"proj": "geos", "lon_0": lon_0, "h": HEIGHT, "a": 6378137, "b": 6356752.3, "sweep": "x", "units": "m"}
    rgba = np.zeros((4, 220, 220), dtype=np.uint8)
    rgba[0], rgba[3] = red, 255
    with rasterio.open(path, "w", driver="GTiff", width=220, height=220, count=4, dtype="uint8",
                       crs=crs, transform=from_origin(-5.5e6, 5.5e6, 50e3, 50e3)) as dst:
        dst.write(rgba)
    return str(path)


def pixel(src, lon: float, lat: float = 0.0) -> list[int]:
    from pyproj import Transformer

    x, y = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform(lon, lat)
    row, col = src.index(x, y)
    return src.read()[:, row, col].tolist()


def test_two_disks_are_joined_at_their_seam_and_published_on_the_web_tile_grid(tmp_path):
    import rasterio

    from georing.mosaic import encode_mosaic, join_renderings

    renders = {
        "goes-east": write_render(tmp_path / "east.tif", EAST, 200),
        "goes-west": write_render(tmp_path / "west.tif", WEST, 100),
    }
    joined = str(tmp_path / "joined.tif")
    join_renderings(renders, joined, slot="2026-11-10T18:00:00+00:00", threads=2, zoom=3)

    with rasterio.open(joined) as src:
        assert src.tags()["GEORING_DISKS"] == "goes-east,goes-west"
        assert (src.width, src.height) == (2048, 2048)
        assert pixel(src, EAST) == [200, 0, 0, 255]
        assert pixel(src, WEST) == [100, 0, 0, 255]
        seam = pixel(src, (EAST + WEST) / 2)
        assert 140 <= seam[0] <= 160 and seam[3] == 255      # feathered
        assert pixel(src, -112.0)[0] == 100                  # outside the Seam, the steeper view alone
        assert pixel(src, 60.0)[3] == 0                      # no satellite sees India
        assert pixel(src, EAST, 84.0)[3] == 0                # beyond the limb

    published = str(tmp_path / "mosaic.tif")
    encode_mosaic(joined, published, threads=2, zoom=3)     # checks its own tile layout

    with rasterio.open(published) as src:
        assert [src.width, *(src.width // f for f in src.overviews(1))] == [2048, 1024, 512]
        assert src.compression.value == "WEBP"
        assert abs(pixel(src, EAST)[0] - 200) <= 6 and pixel(src, 60.0)[3] == 0


def test_a_coarser_imager_takes_over_only_where_it_sees_finer(tmp_path):
    import rasterio

    from georing.mosaic import join_renderings

    renders = {
        "meteosat-0": write_render(tmp_path / "zero.tif", 0.0, 200),
        "meteosat-iodc": write_render(tmp_path / "iodc.tif", 45.5, 100),
    }
    joined = str(tmp_path / "joined.tif")
    join_renderings(renders, joined, slot="2026-11-10T06:00:00+00:00", threads=2, zoom=3)

    with rasterio.open(joined) as src:
        # Meteosat-9 views 30E more steeply, but its 3 km pixels are larger there.
        assert pixel(src, 30.0) == [200, 0, 0, 255]
        assert pixel(src, 75.0) == [100, 0, 0, 255]


def test_a_seam_takes_the_narrower_of_its_two_widths():
    angle = np.full((1, 1), 30.0, dtype=np.float32)
    # 3 degrees apart: inside a 5 degree Seam, outside a 2.5 degree one.
    wide = blend([layer(200, angle), layer(100, angle + 3.0)], widths=[5.0, 5.0])
    narrow = blend([layer(200, angle), layer(100, angle + 3.0)], widths=[5.0, 2.5])
    assert 100 < wide[0, 0, 0] < 200
    assert narrow[0, 0, 0] == 200
