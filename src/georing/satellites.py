"""The Satellite set: the positions that contribute Disks, and where each Disk comes from."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Satellite:
    """One position of the Satellite set."""

    position: str
    platform: str
    reader: str
    # Anonymous S3 bucket in us-east-1, or None for the EUMETSAT Data Store.
    bucket: str | None = None
    collections: tuple[str, ...] = ()
    # The Data Store's files of a product that make the Disk, by their names.
    entries: str = ""
    expected_files: int = 0

    def prefix(self, slot: datetime) -> str:
        """Return the bucket prefix holding the Disk that starts at ``slot``."""
        raise NotImplementedError

    def key_pattern(self, slot: datetime) -> re.Pattern[str]:
        """Return the pattern matching the Disk's files under :meth:`prefix`."""
        raise NotImplementedError


@dataclass(frozen=True)
class Goes(Satellite):
    """A GOES position: one NetCDF file per band per scan."""

    number: int = 0
    bands: tuple[str, ...] = ("C01", "C02", "C03", "C07", "C13")

    def prefix(self, slot: datetime) -> str:
        return f"ABI-L1b-RadF/{slot:%Y/%j/%H}/"

    def key_pattern(self, slot: datetime) -> re.Pattern[str]:
        bands = "|".join(self.bands)
        return re.compile(
            rf"OR_ABI-L1b-RadF-M\d(?:{bands})"
            rf"_G{self.number}_s{slot:%Y%j%H%M}\d{{3}}_.*\.nc$"
        )


@dataclass(frozen=True)
class Himawari(Satellite):
    """Himawari: ten bz2 segments per band."""

    number: int = 9
    bands: tuple[str, ...] = ("B01", "B02", "B03", "B04", "B07", "B13")

    def prefix(self, slot: datetime) -> str:
        return f"AHI-L1b-FLDK/{slot:%Y/%m/%d/%H%M}/"

    def key_pattern(self, slot: datetime) -> re.Pattern[str]:
        bands = "|".join(self.bands)
        return re.compile(
            rf"HS_H{self.number:02d}_{slot:%Y%m%d_%H%M}_(?:{bands})"
            rf"_FLDK_R\d\d_S\d{{4}}\.DAT\.bz2$"
        )


SATELLITE_SET: tuple[Satellite, ...] = (
    Goes("goes-east", "GOES-19", "abi_l1b", bucket="noaa-goes19", number=19, expected_files=5),
    Goes("goes-west", "GOES-18", "abi_l1b", bucket="noaa-goes18", number=18, expected_files=5),
    Himawari("himawari", "Himawari-9", "ahi_hsd", bucket="noaa-himawari9", expected_files=60),
    Satellite(
        "meteosat-0",
        "MTG-I1",
        "fci_l1c_nc",
        # Normal resolution and high resolution: 40 body chunks each. satpy
        # cannot open the trailer chunk, so it is left out.
        collections=("EO:EUM:DAT:0662", "EO:EUM:DAT:0665"),
        entries=r"-BODY-.*\.nc$",
        expected_files=80,
    ),
    Satellite(
        "meteosat-iodc",
        "Meteosat-9",
        "seviri_l1b_native",
        # Indian Ocean Data Coverage: one native-format file per scan.
        collections=("EO:EUM:DAT:MSG:HRSEVIRI-IODC",),
        entries=r"\.nat$",
        expected_files=1,
    ),
)


def by_position(position: str) -> Satellite:
    """Return the satellite serving ``position``."""
    for sat in SATELLITE_SET:
        if sat.position == position:
            return sat
    raise KeyError(position)
