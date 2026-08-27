"""The capture-store layer of `gnr.rebuild`: the ear's object-name grammar,
type-name filtering, capture ordering, and the two store backends — a fake
S3 client for the bucket, a temp directory for the local cache. No
database, no broker."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from gnr.rebuild import (
    LocalCaptureDir,
    RebuildReport,
    S3Eventstore,
    capture_objects,
    parse_object_key,
)


def test_parse_object_key_reads_the_ear_grammar():
    key = "hw1__1/eventstore/20260827/hw1.gnr-g.node.forest-1787846141199-hw1.gnr.ear.json"
    parsed = parse_object_key(key)
    assert parsed is not None
    assert parsed.key == key
    assert parsed.type_name == "g.node.forest"
    assert parsed.persisted_ms == 1787846141199


def test_parse_object_key_refuses_names_outside_the_grammar():
    assert parse_object_key("hw1__1/hw1.gnr.ear-hb-hw1.gnr.ear.json") is None
    assert parse_object_key("_unparsed_some.key-1787846141199-hw1.gnr.ear.txt") is None
    assert parse_object_key("hw1__1/eventstore/20260827/notes.txt") is None


class FakeStore:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys

    def list_keys(self):
        return list(self.keys)

    def read(self, key: str) -> bytes:
        raise AssertionError("listing must not read")


def test_capture_objects_filters_and_orders_by_persisted_ms():
    keys = [
        "x/eventstore/20260827/hw1.gnr-g.node.forest-300-hw1.gnr.ear.json",
        "x/eventstore/20260827/hw1.gnr-g.node.cmd.ack-150-hw1.gnr.ear.json",
        "x/eventstore/20260826/hw1.registrar-g.node.create.cmd-100-hw1.gnr.ear.json",
        "x/eventstore/20260827/hw1.registrar-g.node.reparent.cmd-200-hw1.gnr.ear.json",
        "x/hw1.gnr.ear-hb-hw1.gnr.ear.json",
    ]
    report = RebuildReport()
    ordered = capture_objects(FakeStore(keys), report)
    assert [o.persisted_ms for o in ordered] == [100, 200, 300]
    assert [o.type_name for o in ordered] == [
        "g.node.create.cmd",
        "g.node.reparent.cmd",
        "g.node.forest",
    ]
    assert report.skipped_type_names == {"g.node.cmd.ack"}
    assert report.unparsed_keys == 1


def test_local_capture_dir_reads_flat_and_nested_layouts(tmp_path: Path):
    flat = tmp_path / "a-g.node.create.cmd-1-e.json"
    flat.write_bytes(b"flat")
    nested = tmp_path / "hw1__1" / "eventstore" / "20260827"
    nested.mkdir(parents=True)
    (nested / "b-g.node.forest-2-e.json").write_bytes(b"nested")
    store = LocalCaptureDir(tmp_path)
    keys = list(store.list_keys())
    assert len(keys) == 2
    assert {store.read(k) for k in keys} == {b"flat", b"nested"}


class FakeS3Client:
    """Just enough of boto3's S3 client: day-prefixed listing + get_object."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.prefixes: list[str] = []

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        client = self

        class Paginator:
            def paginate(self, Bucket: str, Prefix: str):
                client.prefixes.append(Prefix)
                keys = sorted(k for k in client.objects if k.startswith(Prefix))
                yield {"Contents": [{"Key": k} for k in keys]} if keys else {}

        return Paginator()

    def get_object(self, Bucket: str, Key: str):
        class Body:
            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self) -> bytes:
                return self.data

        return {"Body": Body(self.objects[Key])}


def test_s3_eventstore_lists_each_day_in_range_and_reads_objects():
    objects = {
        "hw1__1/eventstore/20260826/a-g.node.create.cmd-1-e.json": b"one",
        "hw1__1/eventstore/20260827/a-g.node.forest-2-e.json": b"two",
        "hw1__1/eventstore/20260828/a-g.node.forest-3-e.json": b"outside",
        "d1__1/eventstore/20260827/a-g.node.forest-4-e.json": b"other world",
    }
    client = FakeS3Client(objects)
    store = S3Eventstore(
        client, "gw-seedstore", "hw1__1", date(2026, 8, 26), date(2026, 8, 27)
    )
    keys = list(store.list_keys())
    assert keys == [
        "hw1__1/eventstore/20260826/a-g.node.create.cmd-1-e.json",
        "hw1__1/eventstore/20260827/a-g.node.forest-2-e.json",
    ]
    assert client.prefixes == [
        "hw1__1/eventstore/20260826/",
        "hw1__1/eventstore/20260827/",
    ]
    assert store.read(keys[1]) == b"two"
