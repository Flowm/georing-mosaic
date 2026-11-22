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
from satpy.composites.fill import BackgroundCompositor, DayNightCompositor


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


def untinted(colour, fade):
    """Fade the tint out of ``colour`` (red, green and blue in the first axis) by ``fade``, 0 to 1, keeping its mean."""
    mean = colour.mean(axis=0)
    return mean + (colour - mean) * (1 - fade)


def _ramp(value, limits):
    """Return 0 at ``limits[0]`` and below, 1 at ``limits[1]`` and above, linear between."""
    return ((value - limits[0]) / (limits[1] - limits[0])).clip(0, 1)


def distrust(sunz, satz, brightest, sun, view, reach):
    """Return how far, from 0 to 1, a looked-up colour is not to be trusted.

    It rises as the sun zenith ``sunz`` goes from ``sun[0]`` to ``sun[1]``
    degrees, the view zenith ``satz`` from ``view[0]`` to ``view[1]``, or the
    ``brightest`` band from ``reach[0]`` to ``reach[1]`` percent, whichever
    is furthest.
    """
    return np.maximum(np.maximum(_ramp(sunz, sun), _ramp(satz, view)), _ramp(brightest, reach))


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
    end (over ``top_width``), and over water where the satellite looks into
    the sun's reflection, from none at a glint angle of ``glint_angle[1]``
    degrees to all at ``glint_angle[0]``; the fifth band is the land mask (0
    water, 100 land). The grey is the fourth band, the uncorrected 0.8 um
    one, divided by the sun as if it stood no lower than ``grey_sun_cap``.
    Before that, as the sun zenith goes from ``tint_sun[0]`` to
    ``tint_sun[1]`` degrees, the colour loses its tint and keeps its
    brightness (``untinted``): the table was made under a higher sun. Dark
    pixels keep theirs, cloud and haze lose it, as the colour's mean goes
    from ``tint_bright[0]`` to ``tint_bright[1]`` percent.
    The Recipe (``seviri.yaml``) says why each is where it is.
    """

    def __init__(self, name, *, filename, sun_limit, view_limit, fade_width,
                 table_top, top_width, grey_sun_cap, glint_angle, tint_sun, tint_bright,
                 **kwargs):
        with np.load(Path(__file__).parent / "satpy" / filename) as f:
            self.centres, self.table = f["centres"], f["table"]
        self.sun = (sun_limit, sun_limit + fade_width)
        self.view = (view_limit, view_limit + fade_width)
        self.reach = (table_top, table_top + top_width)
        self.grey_sun_cap = grey_sun_cap
        self.glint_angle = tuple(glint_angle)
        self.tint_sun, self.tint_bright = tuple(tint_sun), tuple(tint_bright)
        super().__init__(name, **kwargs)

    def __call__(self, projectables, nonprojectables=None, **attrs):
        from satpy.modifiers.angles import get_angles

        projectables = self.match_data_arrays(projectables)
        bands = da.stack([p.data for p in projectables[:3]]).rechunk({0: 3})
        colour = da.map_blocks(
            colour_from_table, bands, self.centres, self.table, dtype=bands.dtype,
        )
        sat_azimuth, satz, sun_azimuth, sunz = get_angles(projectables[0])
        colour = untinted(colour, _ramp(sunz.data, self.tint_sun) * _ramp(colour.mean(axis=0), self.tint_bright))
        fade = distrust(sunz.data, satz.data, bands.max(axis=0), self.sun, self.view, self.reach)
        land = projectables[4].squeeze("bands", drop=True) if "bands" in projectables[4].dims else projectables[4]
        glint = glint_angle(sunz.data, satz.data, sun_azimuth.data, sat_azimuth.data)
        fade = np.maximum(fade, near_glint(glint, self.glint_angle) * (1 - land.data / 100).clip(0, 1))
        grey = capped_sun_correction(projectables[3].data, sunz.data, self.grey_sun_cap)
        rgb = [projectables[0].copy(data=toward_grey(colour[i], grey, fade)) for i in range(3)]
        return super().__call__(rgb, **attrs)


class SeenBackground(BackgroundCompositor):
    """satpy's background compositor, but missing wherever a third prerequisite, a band, is.

    The night layer lays the infrared clouds over the city lights, which
    cover every pixel the grid can see. Where the satellite scanned no
    infrared, the lights alone would be drawn there, opaque, and hide the
    neighbour that did see it: Meteosat-9's scans stop rows short of its
    northern limb, and at night that left a black lens over the Barents
    Sea. The clouds cannot say where that is, as satpy's compositing fills
    them everywhere; the infrared band they are made from can.
    """

    def __call__(self, projectables, *args, **kwargs):
        projectables = self.match_data_arrays(projectables)
        seen = projectables[2].notnull()
        return super().__call__(projectables[:2], *args, **kwargs).where(seen)


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
    return _ramp(sunz, sun) * near_glint(glint, angle)


def near_glint(glint, angle):
    """Return how near, from 0 to 1, the view is to the sun's reflection: 1 within ``angle[0]`` degrees, 0 beyond ``angle[1]``."""
    return 1 - _ramp(glint, angle)


def _with_orbit(day):
    """Return the day layer, carrying where the satellite was for satpy's view angles.

    Some day layers lose it in their own compositing (AHI's), and the night
    layer never has it; it is then taken from the grid, which places the
    satellite on the equator at its nominal longitude.
    """
    if day.attrs.get("orbital_parameters"):
        return day
    proj = day.attrs["area"].crs.to_dict()
    day = day.copy()
    day.attrs["orbital_parameters"] = {
        "projection_longitude": proj["lon_0"], "projection_latitude": 0.0, "projection_altitude": proj["h"],
    }
    return day


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
    over water only, as the land mask (0 water, 100 land) says, and only as
    far as the day layer is burnt out: as its brightest band goes from
    ``burnt[0]`` to ``burnt[1]`` (0 to 1). Land under the same sun and view
    keeps its cloud by day, and so does a day layer that is not burnt out.
    """

    def __init__(self, name, *, gain, offset, stretch_start, stretch_end, glare_sun, glare_angle, burnt,
                 **kwargs):
        self.gain, self.offset = tuple(gain), tuple(offset)
        self.stretch = (stretch_start, stretch_end)
        self.glare_sun, self.glare_angle, self.burnt = tuple(glare_sun), tuple(glare_angle), tuple(burnt)
        super().__init__(name, **kwargs)

    def __call__(self, datasets, optional_datasets=None, **attrs):
        import copy

        from satpy.modifiers.angles import get_angles

        datasets = self.match_data_arrays(datasets)
        sat_azimuth, satz, sun_azimuth, sunz = get_angles(_with_orbit(datasets[0]))
        # The land mask is an optional prerequisite only because satpy's
        # day/night compositor takes a third prerequisite for the sun zenith.
        # Without it there is no telling sea from land, and no glare is taken.
        sea_glare = 0.0
        if optional_datasets:
            land = self.match_data_arrays([datasets[0], *optional_datasets])[1]
            land = land.squeeze("bands", drop=True) if "bands" in land.dims else land
            glint = glint_angle(sunz.data, satz.data, sun_azimuth.data, sat_azimuth.data)
            sea_glare = glare(sunz.data, glint, self.glare_sun, self.glare_angle) * (1 - land.data / 100).clip(0, 1)
        # satpy hands its weights and layers from one method to the next, and
        # the sun zenith and glare go with them on a copy made for this call:
        # the compositor itself, which satpy keeps, holds nothing of a render.
        call = copy.copy(self)
        call._sunz, call._glare = sunz, sea_glare
        result = DayNightCompositor.__call__(call, datasets, **attrs)
        # Where the satellite was: the night layer's static images have no
        # orbit, so satpy's merged metadata drops it. The Mosaic needs it
        # (georing.render.satellite_position_tags).
        if orbit := datasets[0].attrs.get("orbital_parameters"):
            result.attrs["orbital_parameters"] = orbit
        return result

    # satpy's own weights, from the sun zenith this call already has: satpy
    # would work it out again over the whole Disk. As when satpy works it out
    # itself, the weights are then masked where neither layer has data.
    def _get_coszen_blending_weights(self, projectables):
        lim_low, lim_high = float(np.cos(np.radians(self.lim_low))), float(np.cos(np.radians(self.lim_high)))
        self._has_sza = False
        coszen = np.cos(np.radians(self._sunz))
        return ((coszen - min(lim_high, lim_low)) / abs(lim_low - lim_high)).clip(0, 1)

    # satpy's own merge, but the bands go through `twilight`.
    def _merge_bands_with_weights(self, day_data, night_data, weights, attrs):
        # Both layers are red, green and blue on every satellite.
        brightest = day_data.sel(bands=["R", "G", "B"]).max("bands")
        weights = weights * (1 - self._glare * _ramp(brightest, self.burnt))
        data = []
        for i, b in enumerate("RGB"):
            band = twilight(day_data.sel(bands=b), night_data.sel(bands=b), self._sunz, weights,
                            self.gain[i], self.offset[i], *self.stretch)
            band.attrs = attrs
            data.append(band)
        return data


def curve(values: np.ndarray, xp: np.ndarray, fp: np.ndarray) -> np.ndarray:
    """Map ``values`` through the curve through points ``xp``, ``fp``, keeping their dtype; for ``map_blocks``."""
    return np.interp(values, xp, fp).astype(values.dtype)


def _recolour(img, source, xp, curves):
    """Replace the colour bands of ``img`` by ``source`` mapped through ``curves``."""
    data = img.data
    xp = np.asarray(xp, dtype=float) / 255
    bands = [
        da.map_blocks(curve, source(band), xp, np.asarray(fp, dtype=float) / 255, dtype=data.dtype)
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

