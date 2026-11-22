from datetime import UTC, datetime

from georing.satellites import attribution, by_position

SLOT = datetime(2026, 11, 10, 18, tzinfo=UTC)


def test_goes_matches_only_the_scan_that_starts_on_the_hour():
    sat = by_position("goes-east")
    pattern = sat.key_pattern(SLOT)
    on_the_hour = "OR_ABI-L1b-RadF-M6C02_G19_s20263141800203_e20263141809512_c20263141809550.nc"
    assert sat.prefix(SLOT) == "ABI-L1b-RadF/2026/314/18/"
    assert pattern.search(sat.prefix(SLOT) + on_the_hour)
    assert not pattern.search(on_the_hour.replace("s20263141800203", "s20263141810203"))
    assert not pattern.search(on_the_hour.replace("C02", "C05"))
    assert not pattern.search(on_the_hour.replace("_G19_", "_G18_"))


def test_himawari_matches_the_ten_segments_of_each_needed_band():
    sat = by_position("himawari")
    pattern = sat.key_pattern(SLOT)
    assert sat.prefix(SLOT) == "AHI-L1b-FLDK/2026/11/10/1800/"
    assert pattern.search("HS_H09_20261110_1800_B03_FLDK_R05_S0710.DAT.bz2")
    assert not pattern.search("HS_H09_20261110_1800_B05_FLDK_R20_S0710.DAT.bz2")
    assert not pattern.search("HS_H09_20261110_1810_B03_FLDK_R05_S0710.DAT.bz2")


def test_a_meteosat_disk_is_the_files_its_reader_opens():
    import re

    fci, seviri = by_position("meteosat-0"), by_position("meteosat-iodc")
    stem = "W_XX-EUMETSAT-Darmstadt,IMG+SAT,MTI1+FCI-1C-RRAD-FDHSI-FD--CHK-"
    assert re.search(fci.entries, f"{stem}BODY---NC4E_C_EUMT_20261110180713_IDPFI_OPE_20261110180007_20261110180017_N_JLS_C_0108_0001.nc")
    assert not re.search(fci.entries, f"{stem}TRAIL---NC4E_C_EUMT_20261110181013_IDPFI_OPE_20261110180007_20261110180924_N_JLS_C_0108_0000.nc")
    assert re.search(seviri.entries, "MSG2-SEVI-MSG15-0100-NA-20261110061239.803000000Z-NA.nat")
    assert not any(re.search(seviri.entries, name) for name in ("EOPMetadata.xml", "manifest.xml"))


def test_the_credit_groups_the_satellites_by_provider_and_says_each_thing_once():
    every = ["goes-east", "goes-west", "himawari", "meteosat-0", "meteosat-iodc"]
    assert attribution(every, 2026) == [
        "GOES-19, GOES-18: NOAA. Himawari-9: JMA, via NOAA. No endorsement by NOAA is implied.",
        "Contains modified EUMETSAT Meteosat data 2026",
    ]
    assert attribution(["meteosat-iodc"], 2027) == ["Contains modified EUMETSAT Meteosat data 2027"]
    assert attribution(["himawari"], 2026) == ["Himawari-9: JMA, via NOAA. No endorsement by NOAA is implied."]
