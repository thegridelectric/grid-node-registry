"""Deterministic id derivation — reproducible ids for a replayable mutation.

A distributed / consensus backend re-executes a command on many validators that
must agree byte-for-byte, so any id that ends up in the **authoritative state**
(edge ids serialize into `g.node.forest`) MUST be derived from the command, never
random. Same discipline the EDD harness needs for reproducible seeds. See executor
"Distributed-readiness".
"""

from __future__ import annotations

import hashlib
import uuid

from gnr.sema.property_format import UUID4Str

# Hash domain-separation tags. These are internal salts — NOT Sema vocabulary
# names / TypeNames — so ids of different kinds derived from the same input never
# collide. They carry no wire meaning; the exact strings only need to be stable
# and distinct. Deliberately slash-delimited so they can't be mistaken for a
# `left.right.dot` Sema name.
_EDGE_DOMAIN = "gnr-det-id/connectivity-edge"


def deterministic_uuid4(seed: str) -> UUID4Str:
    """A deterministic string in uuid4 *format* (version/variant bits set) from a seed.

    `PositionPointGt.id` / edge ids require the uuid4 format; a uuid5 fails it. The
    value is reproducible across runs (SHA-256, not the salted built-in `hash`).
    """
    b = bytearray(hashlib.sha256(seed.encode()).digest()[:16])
    b[6] = (b[6] & 0x0F) | 0x40  # version 4
    b[8] = (b[8] & 0x3F) | 0x80  # variant RFC 4122
    return str(uuid.UUID(bytes=bytes(b)))


def edge_id(from_g_node_id: str, to_g_node_id: str) -> UUID4Str:
    """The deterministic id of the connectivity edge `from → to` — one per endpoint
    pair, matching the unique `(from, to)` constraint."""
    return deterministic_uuid4(f"{_EDGE_DOMAIN}/{from_g_node_id}/{to_g_node_id}")


def command_hash(payload: bytes) -> str:
    """Content address of a mutation command — SHA-256 hex of its canonical bytes."""
    return hashlib.sha256(payload).hexdigest()
