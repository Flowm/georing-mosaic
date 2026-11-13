import json
from datetime import UTC, datetime

from georing.catalogue import Catalogue, mosaic_item
from georing.storage import Directory

SLOT = datetime(2026, 11, 10, 18, tzinfo=UTC)
ALL = ["goes-east", "goes-west", "himawari", "meteosat-0"]


def publish(catalogue: Catalogue, tmp_path, slot: datetime, disks: list[str] = ALL) -> None:
    image = tmp_path / "mosaic.tif"
    image.write_bytes(b"tiff")
    catalogue.publish(image, mosaic_item(slot, disks, [p for p in ALL if p not in disks]))
    catalogue.index()


def read(path) -> dict:
    return json.loads(path.read_text())


def links(document: dict, rel: str) -> list[str]:
    return [link["href"] for link in document["links"] if link["rel"] == rel]


def test_a_slot_is_done_once_its_mosaic_item_exists(tmp_path):
    catalogue = Catalogue(Directory(tmp_path / "out"))
    assert catalogue.mosaic(SLOT) is None
    publish(catalogue, tmp_path, SLOT, ["goes-east", "goes-west", "himawari"])
    item = catalogue.mosaic(SLOT)
    assert item["properties"]["georing:disks"] == ["goes-east", "goes-west", "himawari"]
    assert item["properties"]["georing:missing_disks"] == ["meteosat-0"]


def test_the_item_says_whose_data_the_mosaic_is_made_of():
    item = mosaic_item(SLOT, ["goes-west", "himawari", "meteosat-0"], ["goes-east"])
    assert item["properties"]["georing:attribution"] == [
        "GOES-18 imagery: NOAA. No endorsement by NOAA is implied.",
        "Himawari-9 imagery: Japan Meteorological Agency, distributed by NOAA.",
        "Contains modified EUMETSAT Meteosat data 2026",
    ]
    assert item["assets"]["image"]["href"] == "./georing_mosaic_20261110T1800Z.tif"


def test_every_link_in_the_catalogue_leads_to_a_file(tmp_path):
    out = tmp_path / "out"
    catalogue = Catalogue(Directory(out))
    publish(catalogue, tmp_path, datetime(2026, 11, 6, 3, tzinfo=UTC))
    publish(catalogue, tmp_path, SLOT)

    seen = set()
    todo = [out / "catalog.json"]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        document = read(path)
        for link in document["links"]:
            target = (path.parent / link["href"]).resolve()
            assert target.exists(), f"{path.name} links to missing {link['href']}"
            todo.append(target)
        for asset in document.get("assets", {}).values():
            assert (path.parent / asset["href"]).exists()
    assert {"catalog.json", "collection.json", "georing_mosaic_20261106T0300Z.json",
            "georing_mosaic_20261110T1800Z.json"} <= {p.name for p in seen}


def test_the_collection_lists_every_item_and_latest_names_the_newest_slot(tmp_path):
    out = tmp_path / "out"
    catalogue = Catalogue(Directory(out))
    publish(catalogue, tmp_path, SLOT)
    publish(catalogue, tmp_path, datetime(2026, 11, 10, 19, tzinfo=UTC))
    # A backfilled Slot of an earlier day does not become the latest.
    publish(catalogue, tmp_path, datetime(2026, 11, 7, 6, tzinfo=UTC))

    assert links(read(out / "mosaic/collection.json"), "item") == [
        "./2026/11/07/georing_mosaic_20261107T0600Z.json",
        "./2026/11/10/georing_mosaic_20261110T1800Z.json",
        "./2026/11/10/georing_mosaic_20261110T1900Z.json",
    ]
    assert read(out / "mosaic/collection.json")["extent"]["temporal"]["interval"] == [
        ["2026-11-07T06:00:00Z", "2026-11-10T19:00:00Z"]]
    assert links(read(out / "mosaic/2026/11/10/georing_mosaic_20261110T1800Z.json"), "parent") == [
        "../../../collection.json"]
    latest = read(out / "latest.json")
    assert latest["slot"] == "2026-11-10T19:00:00Z"
    assert latest["mosaic"] == "mosaic/2026/11/10/georing_mosaic_20261110T1900Z.tif"
    assert latest["missing_disks"] == []


def test_publishing_again_replaces_the_mosaic(tmp_path):
    catalogue = Catalogue(Directory(tmp_path / "out"))
    publish(catalogue, tmp_path, SLOT, ["goes-east"])
    publish(catalogue, tmp_path, SLOT, ["goes-east", "goes-west"])
    assert catalogue.mosaic(SLOT)["properties"]["georing:disks"] == ["goes-east", "goes-west"]
    assert not list((tmp_path / "out").rglob("*.part"))


def test_the_collection_follows_what_is_removed_from_the_store(tmp_path):
    out = tmp_path / "out"
    catalogue = Catalogue(Directory(out))
    publish(catalogue, tmp_path, datetime(2026, 11, 7, 6, tzinfo=UTC))
    publish(catalogue, tmp_path, SLOT)
    # As a lifecycle rule would: the oldest Mosaic and its Item go.
    for path in (out / "mosaic/2026/11/07").iterdir():
        path.unlink()

    catalogue.index()

    assert links(read(out / "mosaic/collection.json"), "item") == ["./2026/11/10/georing_mosaic_20261110T1800Z.json"]
    assert read(out / "mosaic/collection.json")["extent"]["temporal"]["interval"] == [
        ["2026-11-10T18:00:00Z", "2026-11-10T18:00:00Z"]]


def test_every_item_link_carries_its_items_datetime(tmp_path):
    out = tmp_path / "out"
    catalogue = Catalogue(Directory(out))
    for slot in (datetime(2026, 11, 7, 6, tzinfo=UTC), SLOT, datetime(2026, 11, 10, 19, tzinfo=UTC)):
        publish(catalogue, tmp_path, slot)
    # Rebuilt after a late Disk, and the oldest removed by a lifecycle rule.
    publish(catalogue, tmp_path, SLOT, ["goes-east", "goes-west"])
    for path in (out / "mosaic/2026/11/07").iterdir():
        path.unlink()
    catalogue.index()

    collection = out / "mosaic/collection.json"
    item_links = [link for link in read(collection)["links"] if link["rel"] == "item"]
    assert [link["datetime"] for link in item_links] == ["2026-11-10T18:00:00Z", "2026-11-10T19:00:00Z"]
    for link in item_links:
        assert link["datetime"] == read(collection.parent / link["href"])["properties"]["datetime"]
