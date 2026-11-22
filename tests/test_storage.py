import io
from datetime import UTC, datetime

import pytest

from georing.catalogue import Catalogue
from georing.storage import Bucket, Directory, open_store

SLOT = datetime(2026, 11, 10, 18, tzinfo=UTC)


class FakeS3:
    """The few calls of boto3's S3 client that a Bucket makes, kept in a dict."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.headers: dict[str, dict] = {}

    def put_object(self, Bucket, Key, Body, **headers):
        self.objects[Bucket, Key] = Body
        self.headers[Key] = headers

    def upload_file(self, filename, bucket, key, ExtraArgs):
        with open(filename, "rb") as file:
            self.put_object(bucket, key, file.read(), **ExtraArgs)

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[Bucket, Key])}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        keys = sorted(k for b, k in self.objects if b == Bucket and k.startswith(Prefix))
        # Two keys to a page, and an empty page as S3 sends for no match.
        return [{"Contents": [{"Key": k} for k in keys[i:i + 2]]} for i in range(0, len(keys), 2)] or [{}]


@pytest.fixture(params=["directory", "bucket"])
def store(request, tmp_path):
    if request.param == "directory":
        return Directory(tmp_path / "out")
    client = FakeS3()
    # Another prefix in the same bucket must stay out of every answer.
    client.put_object("earth", "georing-old/mosaic/2026/11/10/georing_mosaic_20261110T1800Z.json", b"{}")
    return Bucket("earth", "/georing/", client)


def test_a_store_keeps_documents_and_files_under_keys(store, tmp_path):
    product = tmp_path / "product.tif"
    product.write_bytes(b"tiff")

    assert store.read_json("mosaic/a.json") is None
    assert store.list("mosaic/") == []

    store.write_json("mosaic/a.json", {"id": "a"})
    store.put_file(product, "mosaic/a.tif", "image/tiff")
    store.write_json("other/b.json", {"id": "b"})

    assert store.read_json("mosaic/a.json") == {"id": "a"}
    assert store.list("mosaic/") == ["mosaic/a.json", "mosaic/a.tif"]
    assert store.list("") == ["mosaic/a.json", "mosaic/a.tif", "other/b.json"]


def test_a_catalogue_reads_back_what_it_published(store, tmp_path):
    product = tmp_path / "product.tif"
    product.write_bytes(b"tiff")
    catalogue = Catalogue(store)
    catalogue.publish(SLOT, product, ["goes-east", "himawari"], ["goes-west", "meteosat-0"])

    result = catalogue.index()

    assert result == {"latest": "2026-11-10T18:00:00Z"}
    assert catalogue.mosaic(SLOT)["properties"]["georing:disks"] == ["goes-east", "himawari"]
    assert catalogue.items() == ["mosaic/2026/11/10/georing_mosaic_20261110T1800Z.json"]
    assert store.read_json("latest.json")["mosaic"] == "mosaic/2026/11/10/georing_mosaic_20261110T1800Z.tif"
    assert [link["href"] for link in store.read_json("mosaic/collection.json")["links"]
            if link["rel"] == "item"] == ["./2026/11/10/georing_mosaic_20261110T1800Z.json"]


def test_a_bucket_marks_documents_as_never_fresh(tmp_path):
    client = FakeS3()
    bucket = Bucket("earth", "georing", client)
    product = tmp_path / "product.tif"
    product.write_bytes(b"tiff")
    bucket.put_file(product, "mosaic/a.tif", "image/tiff")
    bucket.write_json("latest.json", {})

    assert client.headers["georing/mosaic/a.tif"] == {"ContentType": "image/tiff"}
    assert client.headers["georing/latest.json"] == {"ContentType": "application/json", "CacheControl": "no-cache"}


def test_the_output_url_picks_the_store(tmp_path):
    assert isinstance(open_store(str(tmp_path)), Directory)
    assert open_store("out").root.name == "out"

    bucket = open_store(
        "s3://earth/georing", endpoint_url="http://localhost:9000", access_key_id="key", secret_access_key="secret"
    )
    assert (bucket.bucket, bucket.prefix) == ("earth", "georing")
    assert bucket.client.meta.endpoint_url == "http://localhost:9000"
    assert bucket.client.meta.region_name == "auto"
    with pytest.raises(ValueError, match="path or s3://"):
        open_store("gs://earth/georing")
