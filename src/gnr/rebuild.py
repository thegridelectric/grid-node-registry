"""Rebuild the registry from the ear's capture — the durability path.

The registry's Postgres is a materialized view of the logged command stream;
this module is the restore mechanism, so unlike the one-shot ingest script it
is repo code with tests. A rebuild replays the captured commands in capture
order through the handler core — refusals re-refuse, applies re-apply
byte-identically (deterministic apply) — and treats every captured
`g.node.forest` broadcast as a **checkpoint**: at that stream position,
`get_forest(broadcast.roots)` on the rebuilding registry must equal the
captured broadcast (its send time aside). That single rule witnesses change
broadcasts and periodic snapshots alike. The end state must be
`validate_registry`-clean.

The capture is the ear's eventstore: one object per published message, the
raw payload as its content, and the message identity in the object name —
`<from-alias>-<type-name>-<persisted-ms>-<source>.json`. Two stores hold
that grammar: the S3-compatible bucket the ear writes to (keys
`<world_instance>/eventstore/<YYYYMMDD>/<name>`) and an ear's local retry
cache (a flat directory of names). The replay reads either through
`ObjectStore`; the type name in the object name is what makes listing cheap
and fetching selective.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple, Protocol

from gnr.db.authority import (
    AuthoritySource,
    CreateError,
    PostgresAuthority,
    ReparentError,
)
from gnr.sema.codec import default_codec

CREATE_CMD = "g.node.create.cmd"
REPARENT_CMD = "g.node.reparent.cmd"
FOREST = "g.node.forest"
# What a rebuild consumes; everything else in the capture (verdicts,
# heartbeats, forest requests) is listed and left unread.
REPLAY_TYPE_NAMES = frozenset({CREATE_CMD, REPARENT_CMD, FOREST})


class CaptureObject(NamedTuple):
    """One eventstore object as named by the ear: `key` is what the store
    fetches by; `type_name` and `persisted_ms` are parsed from its name."""

    key: str
    type_name: str
    persisted_ms: int


def parse_object_key(key: str) -> CaptureObject | None:
    """Read the ear's name grammar off a key (any prefix, `.json` suffix):
    `<from-alias>-<type-name>-<persisted-ms>-<source>`. Aliases and type
    names are dotted, never dashed, so the dash split is exact. Returns
    None for a name outside the grammar (an ear's `_unparsed_` files, a
    heartbeat `<alias>-hb-<alias>`) — a rebuild skips those, never guesses."""
    name = key.rsplit("/", 1)[-1]
    if not name.endswith(".json"):
        return None
    parts = name[: -len(".json")].split("-")
    if len(parts) != 4 or not parts[2].isdigit():
        return None
    return CaptureObject(key=key, type_name=parts[1], persisted_ms=int(parts[2]))


class ObjectStore(Protocol):
    """A capture store: list the keys it holds, read one object's bytes."""

    def list_keys(self) -> Iterable[str]: ...

    def read(self, key: str) -> bytes: ...


class LocalCaptureDir:
    """An ear's local cache (or any directory of eventstore objects), read
    recursively so both the flat retry-cache layout and a mirrored
    `<world>/eventstore/<day>/` tree work."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def list_keys(self) -> Iterable[str]:
        return (
            str(p.relative_to(self.root)) for p in sorted(self.root.rglob("*.json"))
        )

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class S3Eventstore:
    """The ear's bucket over an S3-compatible client (AWS or Backblaze B2 —
    the client carries the endpoint). Lists day by day under
    `<world_instance>/eventstore/<YYYYMMDD>/`, `start`..`end` inclusive."""

    def __init__(
        self, client, bucket: str, world_instance: str, start: date, end: date
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.world_instance = world_instance
        self.start = start
        self.end = end

    def list_keys(self) -> Iterable[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        day = self.start
        while day <= self.end:
            prefix = f"{self.world_instance}/eventstore/{day:%Y%m%d}/"
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    yield obj["Key"]
            day += timedelta(days=1)

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()


@dataclass
class RebuildReport:
    applied: int = 0
    refused: int = 0
    checkpoints: int = 0
    mismatches: list[str] = field(default_factory=list)
    skipped_type_names: set[str] = field(default_factory=set)
    unparsed_keys: int = 0

    @property
    def ok(self) -> bool:
        return not self.mismatches


def capture_objects(store: ObjectStore, report: RebuildReport) -> list[CaptureObject]:
    """The replayable objects in a store, in capture order (`persisted_ms`,
    then key for a stable tie-break). Other type names are counted on the
    report as skipped; keys outside the grammar are counted as unparsed."""
    selected: list[CaptureObject] = []
    for key in store.list_keys():
        parsed = parse_object_key(key)
        if parsed is None:
            report.unparsed_keys += 1
        elif parsed.type_name in REPLAY_TYPE_NAMES:
            selected.append(parsed)
        else:
            report.skipped_type_names.add(parsed.type_name)
    return sorted(selected, key=lambda o: (o.persisted_ms, o.key))


def checkpoint_state(forest: dict) -> dict:
    """A broadcast's comparable content: the forest minus its send time. The
    stamp is when the registry spoke, not registry state — a replay speaks
    at a different instant and must still match."""
    return {k: v for k, v in forest.items() if k != "SendTimeMs"}


def replay(
    payloads: Iterable[bytes],
    authority: AuthoritySource,
    report: RebuildReport | None = None,
) -> RebuildReport:
    """Replay published payloads, in capture order, into `authority` (assumed
    empty); see module doc.

    Raises nothing on a command refusal (a captured refusal re-refuses — that
    is the stream agreeing with itself); a broadcast checkpoint mismatch is
    recorded, not raised, so one bad checkpoint doesn't hide the rest.
    """
    report = report if report is not None else RebuildReport()
    # Broadcasts in a real capture interleave loosely with commands (a burst
    # of publishes reaches the ear before the registry's broadcasts of them),
    # but broadcast EMISSION order equals apply order — so captured broadcasts
    # pair FIFO with replay-produced ones; a broadcast matching neither the
    # FIFO head nor current state (the snapshot case) is a real divergence.
    produced: deque[dict] = deque()
    for n, raw in enumerate(payloads, start=1):
        payload = json.loads(raw)
        type_name = payload.get("TypeName")
        if type_name == CREATE_CMD:
            try:
                produced.append(
                    authority.apply_create(default_codec.from_dict(payload)).to_dict()
                )
                report.applied += 1
            except CreateError:
                report.refused += 1
        elif type_name == REPARENT_CMD:
            try:
                produced.append(
                    authority.apply_reparent(default_codec.from_dict(payload)).to_dict()
                )
                report.applied += 1
            except ReparentError:
                report.refused += 1
        elif type_name == FOREST:
            report.checkpoints += 1
            captured = default_codec.from_dict(payload)
            captured_dict = checkpoint_state(captured.to_dict())
            if produced and checkpoint_state(produced[0]) == captured_dict:
                produced.popleft()
            elif (
                checkpoint_state(authority.get_forest(captured.roots).to_dict())
                != captured_dict
            ):
                report.mismatches.append(
                    f"object {n}: forest under {list(captured.roots)!r} diverges "
                    "from the captured broadcast"
                )
        else:
            report.skipped_type_names.add(str(type_name))
    return report


def rebuild(
    store: ObjectStore, authority: AuthoritySource | None = None
) -> RebuildReport:
    """Replay a capture store (authority defaults to the env-configured
    Postgres)."""
    from gnr.settings import Settings

    source = authority or PostgresAuthority(universe=Settings().universe)
    report = RebuildReport()
    objects = capture_objects(store, report)

    def payloads() -> Iterator[bytes]:
        for obj in objects:
            yield store.read(obj.key)

    return replay(payloads(), source, report)
