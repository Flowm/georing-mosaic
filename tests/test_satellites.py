from datetime import UTC, datetime

from georing.satellites import by_position

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
