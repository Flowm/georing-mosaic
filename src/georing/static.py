"""Fetch the static files satpy and pyspectral need, once.

In the worker image this happens at build time; here it happens on first run,
so that a Slot downloads only satellite data.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

# The city lights are not among them: the flow builds them (georing.lights).
STATIC_IMAGES = {
    "gshhs_land_water_mask_3km_i.tif": (
        "https://zenodo.org/records/10076199/files/gshhs_land_water_mask_3km_i.tif",
        "96df83c57416217e191f95dde3d3c1ce0373a8fc220e929228873db246ca3569",
    ),
}


def static_env(static_dir: Path) -> dict[str, str]:
    """Return the environment that points satpy and pyspectral at ``static_dir``."""
    return {
        "SATPY_DATA_DIR": str(static_dir / "satpy"),
        "SATPY_DOWNLOAD_AUX": "False",
        "PSP_CONFIG_FILE": str(static_dir / "pyspectral.yaml"),
    }


def fetch_static(static_dir: str) -> None:
    """Download whatever is missing under ``static_dir``."""
    root = Path(static_dir)

    images = root / "satpy" / "composites"
    images.mkdir(parents=True, exist_ok=True)
    for name, (url, sha256) in STATIC_IMAGES.items():
        path = images / name
        if path.exists():
            continue
        part = path.with_name(name + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "georing"})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request) as src, open(part, "wb") as dst:
            while block := src.read(1 << 20):
                digest.update(block)
                dst.write(block)
        if digest.hexdigest() != sha256:
            part.unlink()
            raise RuntimeError(f"{name}: checksum mismatch from {url}")
        part.rename(path)

    rsr = root / "pyspectral" / "rsr"
    rayleigh = root / "pyspectral" / "rayleigh"
    config = root / "pyspectral.yaml"
    done = root / "pyspectral" / ".complete"
    if not done.exists():
        # Download with the internet allowed, then write the offline config.
        config.write_text(f"rsr_dir: {rsr}\nrayleigh_dir: {rayleigh}\n")
        os.environ["PSP_CONFIG_FILE"] = str(config)
        from pyspectral.utils import download_luts, download_rsr

        download_luts(aerosol_types=["rayleigh_only"])
        download_rsr()
        done.touch()
    config.write_text(
        f"rsr_dir: {rsr}\nrayleigh_dir: {rayleigh}\ndownload_from_internet: False\n"
    )


def main() -> int:
    """Fetch the static files into the directory the settings name."""
    from georing.settings import settings

    fetch_static(str(settings().static))
    print(f"The static files are in {settings().static}.")
    return 0
