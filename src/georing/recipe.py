"""The Recipe's own enhancement steps.

satpy calls these by name from ``src/georing/satpy/enhancements``. Curve points
are written on a 0 to 255 scale, as they are read off an image; the image data
itself runs from 0 to 1.
"""

from __future__ import annotations

import dask.array as da
import numpy as np


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

