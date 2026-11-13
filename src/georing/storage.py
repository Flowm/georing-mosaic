"""Where the products and the catalogue are kept: a directory or an S3 bucket.

``open_store`` picks one from the output URL: a path gives a ``Directory``,
``s3://bucket/prefix`` a ``Bucket``. Both hold files under keys such as
``mosaic/2026/11/10/georing_mosaic_20261110T1800Z.tif``, relative to the
output location.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

JSON = "application/json"


class Directory:
    """A directory on this host."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def read_json(self, key: str) -> dict | None:
        """Return the document at ``key``, or None if there is none."""
        path = self.root / key
        return json.loads(path.read_text()) if path.exists() else None

    def write_json(self, key: str, document: dict) -> None:
        self._replace(key, lambda part: part.write_text(json.dumps(document, indent=2) + "\n"))

    def put_file(self, local: Path, key: str, content_type: str) -> None:
        """Copy the file at ``local`` to ``key``."""
        self._replace(key, lambda part: shutil.copyfile(local, part))

    def list(self, prefix: str) -> list[str]:
        """Return every key that starts with ``prefix``, sorted."""
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in (self.root / prefix).rglob("*")
            if path.is_file() and path.suffix != ".part"
        )

    def _replace(self, key: str, write) -> None:
        # Write under another name first: a reader must never see half a file.
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        write(part)
        part.replace(path)


class Bucket:
    """A prefix in an S3 bucket, on AWS or any service that speaks S3.

    An upload shows up only once it is complete, so nothing is renamed.
    """

    def __init__(self, bucket: str, prefix: str, client):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client

    def read_json(self, key: str) -> dict | None:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"]
        except self.client.exceptions.NoSuchKey:
            return None
        return json.loads(body.read())

    def write_json(self, key: str, document: dict) -> None:
        # Every JSON file here is rewritten as Slots arrive; a cache between
        # the bucket and a reader must ask again each time.
        self.client.put_object(
            Bucket=self.bucket, Key=self._key(key), Body=(json.dumps(document, indent=2) + "\n").encode(),
            ContentType=JSON, CacheControl="no-cache",
        )

    def put_file(self, local: Path, key: str, content_type: str) -> None:
        self.client.upload_file(
            str(local), self.bucket, self._key(key), ExtraArgs={"ContentType": content_type}
        )

    def list(self, prefix: str) -> list[str]:
        start = len(self._key(""))
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self._key(prefix)
        )
        return sorted(entry["Key"][start:] for page in pages for entry in page.get("Contents", []))

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key


def open_store(
    output_url: str,
    *,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
) -> Directory | Bucket:
    """Return the store ``output_url`` names: a path, or ``s3://bucket/prefix``.

    The other arguments are for a bucket only. Without a key and secret,
    boto3 looks for credentials where it usually does.
    """
    url = urlsplit(output_url)
    if url.scheme in ("", "file"):
        return Directory(Path(url.path if url.scheme else output_url))
    if url.scheme != "s3" or not url.netloc:
        raise ValueError(f"output_url must be a path or s3://bucket/prefix, not {output_url!r}")

    import boto3
    from botocore.config import Config

    client = boto3.client(
        # Services other than AWS take any region name; "auto" is the one R2 documents.
        "s3", endpoint_url=endpoint_url, region_name="auto" if endpoint_url else None,
        aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key,
        # boto3 adds a checksum to every upload by default, which not every
        # S3-compatible service accepts.
        config=Config(request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"),
    )

    return Bucket(url.netloc, url.path, client)
