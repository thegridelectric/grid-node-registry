"""Rabbit transport adapter — a thin gwbase actor over the `AuthoritySource` core.

One of the design's two thin adapters (the other is the FastAPI façade): it maps
rabbit messages onto the transport-agnostic `AuthoritySource` handlers and back,
and holds **no** registry logic of its own. The registry is a gwbase
`TransportClass.GridNodeRegistry` (a routing identity) — deliberately NOT a Sema
enum, since transport routing is decoupled from message decoding.

First cut handles the write loop: consume a `g.node.reparent.cmd`, apply it, and
broadcast the resulting `g.node.topology.broadcast`. (The read request/reply
surface — `assert_active`, `get` — needs its own Sema request types and lands
next.)
"""

from __future__ import annotations

import json

from gwbase import Orchestrator, ServiceSettings
from gwbase.transport_encoding import RoutingEnvelope, TransportClass

from gnr.db.authority import AuthoritySource, PostgresAuthority
from gnr.sema.codec import default_codec
from gnr.sema.property_format import LeftRightDot
from gnr.sema.types import GNodeTopologyBroadcast

REPARENT_CMD = "g.node.reparent.cmd"


class GnrRabbit(Orchestrator):
    """The registry as a rabbit actor: consumes commands, broadcasts topology."""

    def __init__(
        self,
        *,
        settings: ServiceSettings,
        authority: AuthoritySource | None = None,
        my_super_alias: LeftRightDot = "d1.super1",
        my_time_coordinator_alias: LeftRightDot = "d1.time",
    ) -> None:
        super().__init__(
            settings=settings,
            transport_class=TransportClass.GridNodeRegistry,
            my_super_alias=my_super_alias,
            my_time_coordinator_alias=my_time_coordinator_alias,
        )
        self.authority: AuthoritySource = authority or PostgresAuthority()

    def process_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        if envelope.type_name == REPARENT_CMD:
            cmd = default_codec.from_dict(json.loads(body))
            broadcast = self.authority.apply_reparent(cmd)
            self.broadcast_topology(broadcast)

    def broadcast_topology(self, broadcast: GNodeTopologyBroadcast) -> None:
        """Publish a topology change on the registry's mic exchange (best-effort)."""
        self.send(
            envelope=self.broadcast_envelope(type_name=broadcast.type_name),
            body=json.dumps(broadcast.to_dict()).encode(),
        )
