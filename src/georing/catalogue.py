"""The static STAC catalogue beside the Mosaics.

It is plain JSON with relative links, so the whole tree can be moved or
served from any prefix:

    catalog.json                      the root
    latest.json                       the newest Slot, for clients that want only that
    mosaic/collection.json            the Collection, which lists every Item
    mosaic/2026/11/10/<id>.json       one Item per Slot, beside its <id>.tif

The catalogue is the record of which Slots are done (ADR 0003). It is kept
in a store (``georing.storage``): a directory or an S3 bucket.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from georing.satellites import Satellite, by_position
from georing.storage import Bucket, Directory

STAC_VERSION = "1.1.0"
COG = "image/tiff; application=geotiff; profile=cloud-optimized"
JSON = "application/json"
# Web Mercator ends at 85.05 degrees.
WORLD = [-180.0, -85.0511, 180.0, 85.0511]


def to_slot(when: datetime | None) -> datetime:
    """Return the Slot ``when`` falls in: its full clock hour in UTC. None means now."""
    when = when or datetime.now(UTC)
    when = when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
    return when.replace(minute=0, second=0, microsecond=0)


def stamp(slot: datetime) -> str:
    """Return the Slot time as it appears in file names."""
    return f"{slot:%Y%m%dT%H%MZ}"


def mosaic_id(slot: datetime) -> str:
    """Return the id of a Slot's Mosaic, which is also its file name without the suffix."""
    return f"georing_mosaic_{stamp(slot)}"


def day_path(slot: datetime) -> str:
    """Return the folder of the Mosaics of a Slot's day, relative to the catalogue root."""
    return f"mosaic/{slot:%Y/%m/%d}"


def attribution(sat: Satellite, year: int) -> str:
    """Return the line the provider of ``sat``'s data asks for."""
    if sat.reader == "abi_l1b":
        return f"{sat.platform} imagery: NOAA. No endorsement by NOAA is implied."
    if sat.reader == "ahi_hsd":
        return f"{sat.platform} imagery: Japan Meteorological Agency, distributed by NOAA."
    return f"Contains modified EUMETSAT Meteosat data {year}"


def mosaic_item(slot: datetime, disks: list[str], missing: list[str]) -> dict:
    """Return the Item of a Mosaic: which Disks it was built from, and whose data they are."""
    west, south, east, north = WORLD
    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "id": mosaic_id(slot),
        "collection": "mosaic",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
        },
        "bbox": WORLD,
        "properties": {
            "datetime": _iso(slot),
            "created": _iso(datetime.now(UTC)),
            "georing:disks": disks,
            "georing:missing_disks": missing,
            "georing:attribution": [attribution(by_position(p), slot.year) for p in disks],
        },
        "assets": {"image": {"href": f"./{mosaic_id(slot)}.tif", "type": COG, "roles": ["data", "visual"]}},
        "links": [
            {"rel": "root", "href": "../../../../catalog.json", "type": JSON},
            {"rel": "parent", "href": "../../../collection.json", "type": JSON},
            {"rel": "collection", "href": "../../../collection.json", "type": JSON},
        ],
    }


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slot_of(key: str) -> datetime:
    """Return the Slot of the Item at ``key``, read off its name."""
    return datetime.strptime(key.rsplit("_", 1)[-1], "%Y%m%dT%H%MZ.json").replace(tzinfo=UTC)


class Catalogue:
    """The catalogue and the Mosaics in one store."""

    def __init__(self, store: Directory | Bucket):
        self.store = store

    def mosaic(self, slot: datetime) -> dict | None:
        """Return the Mosaic Item of ``slot``, or None if the Slot is not done.

        The Item is written after its image, so an Item means both are there.
        """
        return self.store.read_json(f"{day_path(slot)}/{mosaic_id(slot)}.json")

    def items(self) -> list[str]:
        """Return the keys of every Item, oldest Slot first."""
        return [
            key for key in self.store.list("mosaic/")
            if key.rsplit("/", 1)[-1].startswith("georing_") and key.endswith(".json")
        ]

    def publish(self, local: Path, item: dict) -> None:
        """Put the Mosaic at ``local`` in its place and write ``item`` beside it."""
        slot = datetime.strptime(item["properties"]["datetime"], "%Y-%m-%dT%H:%M:%SZ")
        self.store.put_file(local, f"{day_path(slot)}/{item['id']}.tif", COG)
        self.store.write_json(f"{day_path(slot)}/{item['id']}.json", item)

    def index(self) -> dict:
        """Rewrite the Collection, the root and ``latest.json``.

        The Collection lists every Item. The list is read off the store each
        time, so it holds what is there: also after a rebuild, a backfill or a
        lifecycle rule that removed old Mosaics.
        """
        items = self.items()
        self.store.write_json("mosaic/collection.json", {
            "type": "Collection",
            "stac_version": STAC_VERSION,
            "id": "mosaic",
            "description": "The four satellites' views of one Slot joined on one global grid: "
                           "Web Mercator, 611 m per pixel.",
            "license": "other",
            "extent": {
                "spatial": {"bbox": [WORLD]},
                "temporal": {"interval": [[_iso(_slot_of(items[0])), _iso(_slot_of(items[-1]))]]},
            },
            "links": [
                {"rel": "root", "href": "../catalog.json", "type": JSON},
                {"rel": "parent", "href": "../catalog.json", "type": JSON},
                *(
                    {"rel": "item", "href": f"./{key.removeprefix('mosaic/')}", "type": "application/geo+json"}
                    for key in items
                ),
            ],
        })
        self.store.write_json("catalog.json", {
            "type": "Catalog",
            "stac_version": STAC_VERSION,
            "id": "georing",
            "description": "Hourly colour imagery of the whole Earth from geostationary satellites.",
            "links": [
                {"rel": "root", "href": "./catalog.json", "type": JSON},
                {"rel": "child", "href": "./mosaic/collection.json", "type": JSON},
            ],
        })
        newest = self.store.read_json(items[-1])
        latest = {
            "slot": newest["properties"]["datetime"],
            "item": items[-1],
            "mosaic": f"{items[-1].removesuffix('.json')}.tif",
            "disks": newest["properties"]["georing:disks"],
            "missing_disks": newest["properties"]["georing:missing_disks"],
            "updated": _iso(datetime.now(UTC)),
        }
        self.store.write_json("latest.json", latest)
        return {"latest": latest["slot"]}
