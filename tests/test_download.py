from datetime import UTC, datetime
from pathlib import Path

import pytest

from georing import download

SLOT = datetime(2026, 11, 10, 18, tzinfo=UTC)
PREFIX = "ABI-L1b-RadF/2026/314/18/"


def goes_key(band: str, created: str = "20263141809550", start: str = "20263141800203") -> str:
    return f"{PREFIX}OR_ABI-L1b-RadF-M6{band}_G19_s{start}_e20263141809512_c{created}.nc"


class FakeS3:
    """A bucket of the given keys, each holding its own name."""

    def __init__(self, keys: list[str]):
        self.keys = keys
        self.fetched: list[str] = []

    def get_paginator(self, operation):
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": k, "Size": len(k)} for k in self.keys if k.startswith(Prefix)]}

    def download_file(self, bucket, key, path):
        self.fetched.append(key)
        Path(path).write_text(key)


@pytest.fixture
def bucket(monkeypatch):
    s3 = FakeS3([goes_key(band) for band in ("C01", "C02", "C03", "C07", "C13")])
    monkeypatch.setattr(download, "_s3", lambda: s3)
    return s3


def test_a_disk_is_its_needed_bands_of_the_scan_on_the_hour(bucket, tmp_path):
    bucket.keys += [goes_key("C05"), goes_key("C02", start="20263141810203")]

    download.download_disk("goes-east", SLOT.isoformat(), str(tmp_path))

    assert sorted(p.name[18:21] for p in tmp_path.iterdir()) == ["C01", "C02", "C03", "C07", "C13"]
    assert not list(tmp_path.glob("*.part"))
    assert download.disk_available("goes-east", SLOT)


def test_a_disk_with_a_band_missing_is_not_there_yet(bucket, tmp_path):
    bucket.keys.remove(goes_key("C13"))
    assert not download.disk_available("goes-east", SLOT)
    with pytest.raises(download.DiskMissing, match="4 of 5 files"):
        download.download_disk("goes-east", SLOT.isoformat(), str(tmp_path))
    assert "4 of 5 files" in download.poll_disk("goes-east", SLOT.isoformat(), str(tmp_path))

    bucket.keys.append(goes_key("C13"))
    assert download.poll_disk("goes-east", SLOT.isoformat(), str(tmp_path)) is None


def test_the_sources_are_asked_for_many_disks_and_one_that_fails_is_skipped(bucket, monkeypatch):
    def disk_available(position, slot):
        if position == "meteosat-0":
            raise ConnectionError("no answer")
        return position != "himawari"

    monkeypatch.setattr(download, "disk_available", disk_available)
    asked = {SLOT.isoformat(): ["goes-east", "himawari", "meteosat-0"], "2026-11-10T17:00:00+00:00": ["himawari"]}
    assert download.disks_available(asked) == {SLOT.isoformat(): ["goes-east"]}


def test_a_file_already_on_disk_at_its_full_size_is_not_fetched_again(bucket, tmp_path):
    download.download_disk("goes-east", SLOT.isoformat(), str(tmp_path))
    assert len(bucket.fetched) == 5
    bucket.fetched.clear()
    (tmp_path / goes_key("C01").rsplit("/", 1)[-1]).write_text("cut short")

    download.download_disk("goes-east", SLOT.isoformat(), str(tmp_path))

    assert bucket.fetched == [goes_key("C01")]
