import numpy as np
import pytest

from georing.mosaic import blend, glint_penalty, sun_direction, view_zenith

HEIGHT = 35786023.0
EAST, WEST = -75.2, -137.0


def layer(colour: int, zenith: np.ndarray, penalty: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgba = np.zeros((4, *zenith.shape), dtype=np.uint8)
    rgba[0], rgba[3] = colour, 255
    return zenith, rgba, zenith + penalty


def test_view_zenith_is_zero_below_the_satellite_and_90_at_the_limb():
    zenith = view_zenith(np.array([0.0]), np.array([EAST, EAST + 81.3]), EAST, HEIGHT)
    assert zenith[0, 0] == pytest.approx(0, abs=1e-3)
    assert zenith[0, 1] == pytest.approx(90, abs=0.1)


def test_the_india_seam_is_viewed_at_about_80_degrees_from_both_sides():
    meteosat = view_zenith(np.array([0.0]), np.array([70.35]), 0.0, HEIGHT)
    himawari = view_zenith(np.array([0.0]), np.array([70.35]), 140.7, HEIGHT)
    assert meteosat[0, 0] == pytest.approx(himawari[0, 0], abs=1e-3)
    assert 78 < meteosat[0, 0] < 85  # inside the default limit


def test_a_satellite_off_the_equator_sees_the_far_side_more_slantwise():
    # Meteosat-9 at 6.5 S, as on 2026-11-15 at 18:00.
    below = view_zenith(np.array([-6.5]), np.array([46.1]), 46.1, HEIGHT, sat_lat=-6.5)
    assert below[0, 0] == pytest.approx(0, abs=1e-3)
    north = np.array([70.0])
    assert (view_zenith(north, np.array([46.1]), 46.1, HEIGHT, sat_lat=-6.5)[0, 0]
            > view_zenith(north, np.array([46.1]), 46.1, HEIGHT)[0, 0] + 5)


def test_blend_takes_the_steeper_view_and_feathers_only_at_the_seam():
    lon = np.array([-110.0, (EAST + WEST) / 2, -102.0])
    lat = np.array([0.0])
    out = blend([
        layer(200, view_zenith(lat, lon, EAST, HEIGHT)),
        layer(100, view_zenith(lat, lon, WEST, HEIGHT)),
    ])
    assert out[0, 0].tolist() == [100, 150, 200]
    assert out[3, 0].tolist() == [255, 255, 255]


def test_blend_feather_ends_where_the_views_differ_by_the_seam_width():
    near = np.full((1, 1), 30.0, dtype=np.float32)
    out = blend([layer(200, near), layer(100, near + 5.0)])
    assert out[0, 0, 0] == 200


def test_a_satellite_without_data_leaves_the_pixel_to_its_neighbour():
    steep, shallow = np.full((1, 2), 20.0, np.float32), np.full((1, 2), 60.0, np.float32)
    hole = layer(200, steep)
    hole[1][3, 0, 0] = 0
    out = blend([hole, layer(100, shallow)])
    assert out[0, 0].tolist() == [100, 200]
    assert out[3, 0].tolist() == [255, 255]


def test_a_satellite_crossing_its_limit_leaves_no_step_in_colour():
    # One satellite's view goes past the limit while its neighbour, just
    # steeper, stays: its share must fade out, not stop at the limit.
    going = np.arange(83.0, 86.0, 0.05, dtype=np.float32)[None, :]
    out = blend([layer(200, going), layer(100, np.full_like(going, 83.5))])[0, 0].astype(int)
    assert out[0] > 140 and out[-1] == 100
    assert np.abs(np.diff(out)).max() <= 5


def test_a_view_into_the_suns_reflection_gives_way_to_a_neighbour_without():
    steep, shallow = np.full((1, 1), 30.0, np.float32), np.full((1, 1), 45.0, np.float32)
    assert blend([layer(200, steep, penalty=20.0), layer(100, shallow)])[0, 0, 0] == 100
    # Alone, the satellite keeps its glint.
    assert blend([layer(200, steep, penalty=20.0)])[0, 0, 0] == 200


def test_the_sun_stands_over_the_tropic_of_capricorn_in_december():
    from datetime import datetime

    sun = sun_direction(datetime.fromisoformat("2026-12-21T12:00:00+00:00"))
    assert np.degrees(np.arcsin(sun[2])) == pytest.approx(-23.4, abs=0.1)
    assert np.degrees(np.arctan2(sun[1], sun[0])) == pytest.approx(0.0, abs=1.0)  # noon at Greenwich


def test_the_glint_penalty_is_full_at_the_suns_reflection_and_none_far_from_it_or_at_night():
    from datetime import datetime

    sun = sun_direction(datetime.fromisoformat("2026-03-20T12:00:00+00:00"))  # overhead at 0 N, 0 E
    lat, lon = np.array([0.0]), np.array([0.0, 60.0, 180.0])
    # Seen from overhead: the reflection; from 60 E: far off it; at 180 E it is night.
    penalty = glint_penalty(lat, lon, sun, 0.0, HEIGHT)[0]
    assert penalty[0] == pytest.approx(20.0)
    assert penalty[1] == 0.0 and penalty[2] == 0.0


def test_a_pixel_no_satellite_sees_stays_transparent():
    empty = layer(200, np.full((1, 1), 20.0, np.float32))
    empty[1][3] = 0
    assert blend([empty, empty])[:, 0, 0].tolist() == [0, 0, 0, 0]


# -- the join and encode steps, on two small Disks ---------------------------


def write_render(path, lon_0: float, red: int, tags: dict | None = None) -> str:
    """Write a 220 px full-disk render of one colour, as the render step's lossless copy."""
    import rasterio
    from rasterio.transform import from_origin

    crs = {"proj": "geos", "lon_0": lon_0, "h": HEIGHT, "a": 6378137, "b": 6356752.3, "sweep": "x", "units": "m"}
    rgba = np.zeros((4, 220, 220), dtype=np.uint8)
    rgba[0], rgba[3] = red, 255
    with rasterio.open(path, "w", driver="GTiff", width=220, height=220, count=4, dtype="uint8",
                       crs=crs, transform=from_origin(-5.5e6, 5.5e6, 50e3, 50e3)) as dst:
        dst.write(rgba)
        dst.update_tags(**(tags or {}))
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
    # Night over the Pacific, so that no glint moves the Seam.
    join_renderings(renders, joined, slot="2026-11-10T06:00:00+00:00", threads=2, zoom=3)

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


def test_each_pixel_comes_from_the_satellite_that_sees_it_most_steeply(tmp_path):
    import rasterio

    from georing.mosaic import join_renderings

    renders = {
        "meteosat-0": write_render(tmp_path / "zero.tif", 0.0, 200),
        "meteosat-iodc": write_render(tmp_path / "iodc.tif", 45.5, 100),
    }
    joined = str(tmp_path / "joined.tif")
    join_renderings(renders, joined, slot="2026-11-10T06:00:00+00:00", threads=2, zoom=3)

    with rasterio.open(joined) as src:
        # The Seam lies halfway, at 22.75E; Meteosat-9's coarser pixels do not move it.
        assert pixel(src, 10.0) == [200, 0, 0, 255]
        assert pixel(src, 35.0) == [100, 0, 0, 255]


def test_the_join_takes_a_satellite_where_it_actually_was(tmp_path):
    import rasterio

    from georing.mosaic import join_renderings, satellite_positions

    at_equator = write_render(tmp_path / "nominal.tif", 45.5, 100)
    south = write_render(tmp_path / "south.tif", 45.5, 100, tags={
        "GEORING_SATELLITE_LON": "45.5", "GEORING_SATELLITE_HEIGHT": str(HEIGHT), "GEORING_SATELLITE_LAT": "-10"})
    assert satellite_positions(at_equator) == [(45.5, HEIGHT, 0.0)]
    assert satellite_positions(south) == [(45.5, HEIGHT, 0.0), (45.5, HEIGHT, -10.0)]
    for path, far_north_seen in ((at_equator, True), (south, False)):
        joined = str(tmp_path / "joined.tif")
        join_renderings({"meteosat-iodc": path}, joined, slot="2026-11-15T18:00:00+00:00", threads=2, zoom=3)
        with rasterio.open(joined) as src:
            # 74N is seen at 83 degrees from the equator, at 93 from 10 S: the
            # satellite did not see it. 74S at 83 and at 72: seen. 78S at 87 and
            # at 78: the satellite saw it, but its grid holds nothing there.
            assert (pixel(src, 45.5, 74.0)[3] == 255) is far_north_seen
            assert pixel(src, 45.5, -74.0)[3] == 255
            assert pixel(src, 45.5, -78.0)[3] == 0
