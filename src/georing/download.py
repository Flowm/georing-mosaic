"""Download the files of one Disk to the scratch directory."""

from __future__ import annotations

import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from georing.satellites import Satellite, by_position


class DiskMissing(RuntimeError):
    """The source does not hold a complete Disk for the Slot."""


def download_disk(position: str, slot: str, dest: str) -> None:
    """Download the Disk of ``position`` that starts at ``slot`` into ``dest``.

    Files already present at their full size are kept. Raises ``DiskMissing``
    while the source does not hold the whole Disk.
    """
    sat = by_position(position)
    when = datetime.fromisoformat(slot)
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    files = _from_bucket(sat, when, out) if sat.bucket else _from_eumetsat(sat, when, out)
    if files != sat.expected_files:
        raise DiskMissing(f"{position}: {files} of {sat.expected_files} files for {slot}")


def poll_disk(position: str, slot: str, dest: str) -> str | None:
    """Download the Disk as ``download_disk`` does; return None, or what the source still lacks.

    The step the flow asks with, minute after minute: a Disk that is not
    there yet is the usual answer and not an error.
    """
    try:
        download_disk(position, slot, dest)
    except DiskMissing as lacking:
        return str(lacking)
    return None


def disk_available(position: str, slot: datetime) -> bool:
    """Return whether the source holds the whole Disk of ``position`` for ``slot``."""
    sat = by_position(position)
    if sat.bucket:
        return len(_bucket_objects(_s3(), sat, slot)) == sat.expected_files
    try:
        return len(_eumetsat_entries(sat, slot)) == sat.expected_files
    except DiskMissing:
        return False


def disks_available(wanted: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return, of the Disks asked for by Slot time, those their sources hold whole.

    A source that cannot be asked counts as not holding the Disk.
    """
    found = {}
    for slot, positions in wanted.items():
        available = []
        for position in positions:
            try:
                if disk_available(position, datetime.fromisoformat(slot)):
                    available.append(position)
            except Exception as error:  # noqa: BLE001 (whatever the source's client raises)
                print(f"Could not ask for the Disk of {position} for {slot}: {error!r}", file=sys.stderr)
        if available:
            found[slot] = available
    return found


def _s3():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name="us-east-1",
        config=Config(signature_version=UNSIGNED, max_pool_connections=16),
    )


def _bucket_objects(s3, sat: Satellite, slot: datetime) -> list[dict]:
    pattern = sat.key_pattern(slot)
    objects = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=sat.bucket, Prefix=sat.prefix(slot)
    ):
        objects += [o for o in page.get("Contents", []) if pattern.search(o["Key"])]
    return objects


def _from_bucket(sat: Satellite, slot: datetime, out: Path) -> int:
    """Fetch the Disk's files that the bucket holds; return how many there are."""
    s3 = _s3()
    objects = _bucket_objects(s3, sat, slot)

    def fetch(obj: dict) -> None:
        path = out / obj["Key"].rsplit("/", 1)[-1]
        if path.exists() and path.stat().st_size == obj["Size"]:
            return
        # boto3 writes under another name and renames when the file is whole.
        s3.download_file(sat.bucket, obj["Key"], str(path))

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fetch, objects))
    return len(objects)


def _eumetsat_entries(sat: Satellite, slot: datetime) -> list[tuple]:
    """Return ``(product, entry)`` for every file of the Disk in the Data Store."""
    import eumdac

    token = eumdac.AccessToken(
        (os.environ["EUMETSAT_CONSUMER_KEY"], os.environ["EUMETSAT_CONSUMER_SECRET"])
    )
    store = eumdac.DataStore(token)

    jobs = []
    for collection_id in sat.collections:
        found = store.get_collection(collection_id).search(
            dtstart=slot, dtend=slot + timedelta(minutes=10)
        )
        # The scan that starts on the hour: sensing begins seconds past it.
        products = [
            p for p in found
            if slot <= p.sensing_start.replace(tzinfo=slot.tzinfo) < slot + timedelta(minutes=1)
        ]
        if len(products) != 1:
            raise DiskMissing(f"{sat.position}: {len(products)} products in {collection_id}")
        product = products[0]
        jobs += [(product, e) for e in product.entries if re.search(sat.entries, e)]
    return jobs


def _from_eumetsat(sat: Satellite, slot: datetime, out: Path) -> int:
    """Fetch the Disk's files that the Data Store holds; return how many there are."""
    jobs = _eumetsat_entries(sat, slot)

    def fetch(job) -> None:
        product, entry = job
        path = out / entry.rsplit("/", 1)[-1]
        if path.exists():
            return
        part = path.with_name(path.name + ".part")
        with product.open(entry=entry) as src, open(part, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        part.rename(path)

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(fetch, jobs))
    return len(jobs)
