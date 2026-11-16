"""The Recipe's own steps: compositors, and enhancement steps.

satpy calls these by name from ``src/georing/satpy``. Curve points are
written on a 0 to 255 scale, as they are read off an image; the image data
itself runs from 0 to 1.
"""

from __future__ import annotations

from pathlib import Path

import dask.array as da
import numpy as np
from satpy.composites.core import GenericCompositor
from satpy.composites.fill import (
    DayNightCompositor,
    _get_band_names,
    _get_single_band_data,
)


def colour_from_table(bands: np.ndarray, centres: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Look up the colour of ``bands`` in ``table``, between its bins.

    ``bands`` holds three bands in its first axis; ``centres`` holds, per
    band, the values the table's bins stand for, rising; ``table`` holds,
    for red, green and blue, the colour at each combination of bins. Values
    between bins are interpolated linearly, and values beyond the first or
    last bin take that bin's colour. A pixel missing in any band is missing.
    """
    from scipy.ndimage import map_coordinates

    shape = bands.shape[1:]
    flat = bands.reshape(3, -1)
    seen = np.isfinite(flat).all(axis=0)
    index = [np.interp(band[seen], c, np.arange(c.size)) for band, c in zip(flat, centres, strict=True)]
    colour = np.full(flat.shape, np.nan, dtype=bands.dtype)
    for channel, values in zip(colour, table, strict=True):
        channel[seen] = map_coordinates(values, index, order=1, mode="nearest")
    return colour.reshape(3, *shape)


def toward_grey(colour, grey, fade):
    """Fade a looked-up colour to the neutral ``grey`` by ``fade``, from 0 (none) to 1 (all)."""
    return colour * (1 - fade) + grey * fade


def distrust(sunz, satz, brightest, sun, view, reach):
    """Return how far, from 0 to 1, a looked-up colour is not to be trusted.

    It rises as the sun zenith ``sunz`` goes from ``sun[0]`` to ``sun[1]``
    degrees, the view zenith ``satz`` from ``view[0]`` to ``view[1]``, or the
    ``brightest`` band from ``reach[0]`` to ``reach[1]`` percent, whichever
    is furthest.
    """
    def ramp(value, limits):
        return ((value - limits[0]) / (limits[1] - limits[0])).clip(0, 1)

    return np.maximum(np.maximum(ramp(sunz, sun), ramp(satz, view)), ramp(brightest, reach))


def capped_sun_correction(reflectance, sunz, cap):
    """Divide a reflectance by the cosine of the sun zenith, the sun taken no lower than ``cap`` degrees."""
    return reflectance / np.cos(np.radians(np.minimum(sunz, cap)))


class ColourTable(GenericCompositor):
    """Make red, green and blue from three other bands by a look-up table.

    SEVIRI has no blue or green band. ``georing-fit-colour`` tabulates the
    colour MTG-I1 shows for each combination of SEVIRI's three day bands,
    from what both satellites see at the same time, and writes the table to
    ``filename`` beside the Recipe. Reflectances are in percent, as satpy
    gives them.

    Where the table is not to be trusted the colour fades to a neutral grey
    (``distrust``): beyond a view of ``view_limit`` degrees from vertical,
    beyond a sun of ``sun_limit`` (each over ``fade_width`` degrees), and
    where the brightest band goes past ``table_top`` percent, the table's
    end (over ``top_width``). There the bands, divided by a low sun or seen
    along the limb, reach combinations the table never saw (it was learnt
    within 65 and 70 degrees), and its edges, filled by a polynomial, are
    orange. The view's fade starts at 58, short of the table's limit: on
    Meteosat-9's southern limb the colour turned salmon from 61. The sun's
    fade starts at 80, where the night layer comes in: from 70 it greyed
    dusk that CIRA keeps coloured. The grey is the fourth band,
    the uncorrected 0.8 um one, divided by the sun as if it stood no lower
    than ``grey_sun_cap``: the Recipe's own correction multiplies it by up to
    six there and turned the limb white where CIRA's is a muted grey.
    """

    def __init__(self, name, filename=None, sun_limit=80.0, view_limit=58.0, fade_width=8.0,
                 table_top=110.0, top_width=20.0, grey_sun_cap=60.0, **kwargs):
        with np.load(Path(__file__).parent / "satpy" / filename) as f:
            self.centres, self.table = f["centres"], f["table"]
        self.sun = (sun_limit, sun_limit + fade_width)
        self.view = (view_limit, view_limit + fade_width)
        self.reach = (table_top, table_top + top_width)
        self.grey_sun_cap = grey_sun_cap
        super().__init__(name, **kwargs)

    def __call__(self, projectables, nonprojectables=None, **attrs):
        from satpy.modifiers.angles import get_angles

        projectables = self.match_data_arrays(projectables)
        bands = da.stack([p.data for p in projectables[:3]]).rechunk({0: 3})
        colour = da.map_blocks(
            colour_from_table, bands, self.centres, self.table, dtype=bands.dtype,
        )
        _, satz, _, sunz = get_angles(projectables[0])
        fade = distrust(sunz.data, satz.data, bands.max(axis=0), self.sun, self.view, self.reach)
        grey = capped_sun_correction(projectables[3].data, sunz.data, self.grey_sun_cap)
        rgb = [projectables[0].copy(data=toward_grey(colour[i], grey, fade)) for i in range(3)]
        return super().__call__(rgb, **attrs)


def twilight(day, night, sunz, weight, gain, offset, start, end, gamma=2.2):
    """Join one channel of the day and night layers across the terminator.

    ``day`` and ``night`` are display values from 0 to 1, ``sunz`` the sun
    zenith in degrees and ``weight`` the day layer's share of the blend.
    From ``start`` to ``end`` degrees the day layer's contrast is stretched
    in, on a smooth step: multiplied by ``gain`` less ``offset`` (on 0 to
    255), held beyond. The layers are then mixed as light, decoded with
    ``gamma``, so neither greys the other where they overlap.
    """
    t = ((sunz - start) / (end - start)).clip(0, 1)
    ramp = t * t * (3 - 2 * t)
    day = ((1 + (gain - 1) * ramp) * day - offset / 255 * ramp).clip(0, 1)
    night = night.clip(0, 1)
    return (weight * day**gamma + (1 - weight) * night**gamma) ** (1 / gamma)


def glint_angle(sunz, satz, sun_azimuth, sat_azimuth):
    """Return the angle, in degrees, between the view and the sun's mirror image in level ground.

    All four angles are in degrees, as seen from the ground: zeniths from
    vertical, azimuths of the sun and of the satellite. 0 is the view
    straight into the sun's reflection.
    """
    s, v = np.radians(sunz), np.radians(satz)
    cos = np.cos(s) * np.cos(v) - np.sin(s) * np.sin(v) * np.cos(np.radians(sun_azimuth - sat_azimuth))
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def glare(sunz, glint, sun, angle):
    """Return how far, from 0 to 1, a low sun's glare outshines the ground.

    It rises as the sun zenith ``sunz`` goes from ``sun[0]`` to ``sun[1]``
    degrees, times as the glint angle ``glint`` falls from ``angle[1]`` to
    ``angle[0]``.
    """
    def ramp(value, limits):
        return ((value - limits[0]) / (limits[1] - limits[0])).clip(0, 1)

    return ramp(sunz, sun) * (1 - ramp(glint, angle))


def _with_orbit(datasets):
    """Return the first dataset, carrying where the satellite was for satpy's view angles.

    Some day layers lose it in their own compositing (AHI's); it is then
    taken from another layer, or else from the grid, which places the
    satellite on the equator at its nominal longitude.
    """
    first = datasets[0]
    if first.attrs.get("orbital_parameters"):
        return first
    orbit = next((d.attrs["orbital_parameters"] for d in datasets if d.attrs.get("orbital_parameters")), None)
    if orbit is None:
        proj = first.attrs["area"].crs.to_dict()
        orbit = {"projection_longitude": proj["lon_0"], "projection_latitude": 0.0, "projection_altitude": proj["h"]}
    first = first.copy()
    first.attrs["orbital_parameters"] = orbit
    return first


class TwilightCompositor(DayNightCompositor):
    """satpy's day/night compositor, with the day layer's low-sun haze taken out.

    The low-sun day layer carries Rayleigh light the correction leaves in: a
    veil over dark sea and blue in the cloud shadows, where CIRA's GeoColor
    keeps its contrast and its shadows dark. ``gain`` and ``offset`` hold,
    for red, green and blue, the stretch that takes it out, more in blue as
    the haze is blue; ``stretch_start`` and ``stretch_end`` are the sun
    zeniths it ramps in between. The blend between ``lim_low`` and
    ``lim_high`` follows satpy's weights but mixes the layers as light (see
    `twilight`).

    Where the satellite looks into a low sun's reflection over the sea,
    along its limb at dawn or dusk, the water throws so much light back that
    the day layer, divided by the low sun, burns out to white; nothing of the
    sea or its cloud shows through. There the night layer comes in too: the
    day layer's share falls by `glare`, from ``glare_sun`` (sun zeniths,
    from none to all) and ``glare_angle`` (glint angles, from all to none),
    over water only, as the optional land mask (0 water, 100 land) says.
    Land under the same sun and view keeps its cloud by day. Without
    ``glare_sun`` there is no such fade.
    """

    def __init__(self, name, gain=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0),
                 stretch_start=76.0, stretch_end=78.0, gamma=2.2,
                 glare_sun=None, glare_angle=(20.0, 40.0), **kwargs):
        self.gain, self.offset = tuple(gain), tuple(offset)
        self.stretch = (stretch_start, stretch_end)
        self.gamma = gamma
        self.glare_sun, self.glare_angle = glare_sun, tuple(glare_angle)
        super().__init__(name, **kwargs)

    def __call__(self, datasets, optional_datasets=None, **attrs):
        datasets = self.match_data_arrays(datasets)
        land = self.match_data_arrays([datasets[0], *optional_datasets])[1] if optional_datasets else None
        if len(datasets) > 2:
            self._sunz = datasets[2]
        else:
            from satpy.modifiers.angles import get_cos_sza

            self._sunz = np.rad2deg(np.arccos(get_cos_sza(datasets[0])))
        self._glare = None
        if self.glare_sun is not None:
            from satpy.modifiers.angles import get_angles

            sat_azimuth, satz, sun_azimuth, sunz = get_angles(_with_orbit(datasets))
            glint = glint_angle(sunz.data, satz.data, sun_azimuth.data, sat_azimuth.data)
            self._glare = glare(sunz.data, glint, self.glare_sun, self.glare_angle)
            if land is not None:
                land = land.squeeze("bands", drop=True) if "bands" in land.dims else land
                self._glare = self._glare * (1 - land.data / 100).clip(0, 1)
        result = super().__call__(datasets, **attrs)
        # Where the satellite was: the night layer's static images have no
        # orbit, so satpy's merged metadata drops it. The Mosaic needs it
        # (georing.render.satellite_position_tags).
        if orbit := datasets[0].attrs.get("orbital_parameters"):
            result.attrs["orbital_parameters"] = orbit
        return result

    # satpy's own merge, but red, green and blue go through `twilight`.
    def _merge_bands_with_weights(self, day_data, night_data, weights, attrs):
        if self._glare is not None:
            weights = weights * (1 - self._glare)
        data = []
        for b in _get_band_names(day_data, night_data):
            day_band = _get_single_band_data(day_data, b)
            night_band = _get_single_band_data(night_data, b)
            name = str(b.values)
            if name in ("R", "G", "B"):
                i = "RGB".index(name)
                band = twilight(day_band, night_band, self._sunz, weights, self.gain[i], self.offset[i],
                                *self.stretch, gamma=self.gamma)
            else:
                band = day_band * weights + night_band * (1 - weights)
            band.attrs = attrs
            data.append(band)
        return data


def _interp(values: np.ndarray, xp: np.ndarray, fp: np.ndarray) -> np.ndarray:
    return np.interp(values, xp, fp).astype(values.dtype)


def _recolour(img, source, xp, curves):
    """Replace the colour bands of ``img`` by ``source`` mapped through ``curves``."""
    data = img.data
    xp = np.asarray(xp, dtype=float) / 255
    bands = [
        da.map_blocks(_interp, source(band), xp, np.asarray(fp, dtype=float) / 255, dtype=data.dtype)
        for band, fp in zip("RGB", curves, strict=True)
    ]
    if "A" in data["bands"].values:
        bands.append(data.sel(bands="A").data)
    data.data = da.stack(bands)
    return data


def channel_curves(img, xp, red, green, blue, **kwargs):
    """Map each colour channel through its own tone curve.

    ``xp`` holds the input levels; ``red``, ``green`` and ``blue`` hold what
    each channel becomes at those levels.
    """
    return _recolour(img, lambda band: img.data.sel(bands=band).data, xp, (red, green, blue))


def uniform_luminance(img, level, **kwargs):
    """Give every pixel of a luminance-alpha image the same luminance.

    ``level`` is on a 0 to 255 scale. The alpha band, which carries the
    information, is kept, and so are missing pixels. This makes the infrared
    cloud layer a white sheet whose opacity follows the cloud-top temperature,
    as in CIRA's GeoColor (Miller et al. 2020, Eq. 8).
    """
    data = img.data
    lum = data.sel(bands="L").data
    bands = [da.where(da.isnan(lum), lum, np.asarray(level / 255, dtype=lum.dtype))]
    bands += [data.sel(bands=b).data for b in data["bands"].values if b != "L"]
    data.data = da.stack(bands)
    return data

