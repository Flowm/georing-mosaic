"""The Recipe's own steps: a compositor, and enhancement steps.

satpy calls these by name from ``src/georing/satpy``. Curve points are
written on a 0 to 255 scale, as they are read off an image; the image data
itself runs from 0 to 1.
"""

from __future__ import annotations

from pathlib import Path

import dask.array as da
import numpy as np
from satpy.composites.core import GenericCompositor


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

