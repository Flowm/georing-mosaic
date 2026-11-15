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


class ColourTable(GenericCompositor):
    """Make red, green and blue from three other bands by a look-up table.

    SEVIRI has no blue or green band. ``georing-fit-colour`` tabulates the
    colour MTG-I1 shows for each combination of SEVIRI's three day bands,
    from what both satellites see at the same time, and writes the table to
    ``filename`` beside the Recipe. Reflectances are in percent, as satpy
    gives them.
    """

    def __init__(self, name, filename=None, **kwargs):
        with np.load(Path(__file__).parent / "satpy" / filename) as f:
            self.centres, self.table = f["centres"], f["table"]
        super().__init__(name, **kwargs)

    def __call__(self, projectables, nonprojectables=None, **attrs):
        projectables = self.match_data_arrays(projectables)
        bands = da.stack([p.data for p in projectables]).rechunk({0: 3})
        colour = da.map_blocks(
            colour_from_table, bands, self.centres, self.table, dtype=bands.dtype,
        )
        rgb = [projectables[0].copy(data=colour[i]) for i in range(3)]
        return super().__call__(rgb, **attrs)


def twilight(day, night, sunz, weight, gain, offset, start, end, gamma=2.2):
    """Join one channel of the day and night layers across the terminator.

    ``day`` and ``night`` are display values from 0 to 1, ``sunz`` the sun
    zenith in degrees and ``weight`` the day layer's share of the blend.
    From ``start`` to ``end`` degrees the day layer's contrast is stretched
    in: multiplied by ``gain`` less ``offset`` (on 0 to 255), held beyond.
    The layers are then mixed as light, decoded with ``gamma``, so neither
    greys the other where they overlap.
    """
    ramp = ((sunz - start) / (end - start)).clip(0, 1)
    day = ((1 + (gain - 1) * ramp) * day - offset / 255 * ramp).clip(0, 1)
    night = night.clip(0, 1)
    return (weight * day**gamma + (1 - weight) * night**gamma) ** (1 / gamma)


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
    """

    def __init__(self, name, gain=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0),
                 stretch_start=76.0, stretch_end=78.0, gamma=2.2, **kwargs):
        self.gain, self.offset = tuple(gain), tuple(offset)
        self.stretch = (stretch_start, stretch_end)
        self.gamma = gamma
        super().__init__(name, **kwargs)

    def __call__(self, datasets, optional_datasets=None, **attrs):
        datasets = self.match_data_arrays(datasets)
        if len(datasets) > 2:
            self._sunz = datasets[2]
        else:
            from satpy.modifiers.angles import get_cos_sza

            self._sunz = np.rad2deg(np.arccos(get_cos_sza(datasets[0])))
        return super().__call__(datasets, optional_datasets=optional_datasets, **attrs)

    # satpy's own merge, but red, green and blue go through `twilight`.
    def _merge_bands_with_weights(self, day_data, night_data, weights, attrs):
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


def colour_by_brightness(img, xp, red, green, blue, **kwargs):
    """Colour an image by its own brightness.

    ``xp`` holds brightness levels, the mean of the three channels; ``red``,
    ``green`` and ``blue`` hold the colour given to each level. The image's
    own hue is dropped.
    """
    brightness = img.data.sel(bands=["R", "G", "B"]).mean("bands").data
    return _recolour(img, lambda band: brightness, xp, (red, green, blue))


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

