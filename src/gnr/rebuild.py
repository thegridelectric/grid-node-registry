"""Rebuild the registry from a captured message stream — the durability path.

The registry's Postgres is a materialized view of the logged command stream
(executor *Durability*); this module is the restore mechanism, so unlike the
one-shot ingest script it is repo code with tests. A rebuild replays the
captured commands in capture order through the handler core — refusals
re-refuse, applies re-apply byte-identically (deterministic apply) — and
treats every captured `g.node.forest` broadcast as a **checkpoint**: at that
stream position, `get_forest(broadcast.roots)` on the rebuilding registry
must equal the captured broadcast exactly. That single rule witnesses change
broadcasts and periodic snapshots alike. The end state must be
`validate_registry`-clean.

Capture format (provisional until the OPS-443 ear-capture format settles):
JSON Lines, each line an object with at least `"body"` — the raw utf-8
message payload as published. Extra fields (routing key, capture metadata)
are ignored. Order in the file is capture order.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

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


@dataclass
class RebuildReport:
    applied: int = 0
    refused: int = 0
    checkpoints: int = 0
    mismatches: list[str] = field(default_factory=list)
    skipped_type_names: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def replay(capture_lines: Iterable[str], authority: AuthoritySource) -> RebuildReport:
    """Replay a capture stream into `authority` (assumed empty); see module doc.

    Raises nothing on a command refusal (a captured refusal re-refuses — that
    is the stream agreeing with itself); a broadcast checkpoint mismatch is
    recorded, not raised, so one bad checkpoint doesn't hide the rest.
    """
    report = RebuildReport()
    # Broadcasts in a real capture interleave loosely with commands (a burst
    # of publishes reaches the ear before the registry's broadcasts of them),
    # but broadcast EMISSION order equals apply order — so captured broadcasts
    # pair FIFO with replay-produced ones; a broadcast matching neither the
    # FIFO head nor current state (the snapshot case) is a real divergence.
    produced: deque[dict] = deque()
    for n, line in enumerate(capture_lines, start=1):
        line = line.strip()
        if not line:
            continue
        payload = json.loads(json.loads(line)["body"])
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
            captured_dict = captured.to_dict()
            if produced and produced[0] == captured_dict:
                produced.popleft()
            elif authority.get_forest(captured.roots).to_dict() != captured_dict:
                report.mismatches.append(
                    f"line {n}: forest under {list(captured.roots)!r} diverges "
                    "from the captured broadcast"
                )
        else:
            report.skipped_type_names.add(str(type_name))
    return report


def rebuild_from_file(path: str, authority: AuthoritySource | None = None) -> RebuildReport:
    """Replay the JSONL capture at `path` (authority defaults to the
    env-configured Postgres)."""
    from gnr.settings import Settings

    source = authority or PostgresAuthority(universe=Settings().universe)
    with open(path, encoding="utf-8") as f:
        return replay(f, source)
