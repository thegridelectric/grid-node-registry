"""Rabbit transport adapter — a thin gwbase actor over the `AuthoritySource` core.

One of the design's two thin adapters (the other is the FastAPI façade): it maps
rabbit messages onto the transport-agnostic `AuthoritySource` handlers and back,
and holds **no** registry logic of its own. The registry is a gwbase
`TransportClass.GridNodeRegistry` (a routing identity) — deliberately NOT a Sema
enum, since transport routing is decoupled from message decoding.

First cut handles the write loop: consume a `g.node.reparent.cmd`, apply it, and
broadcast the resulting `g.node.forest` (the affected subtree). (The read
request/reply surface — `g.node.forest.request` → `g.node.forest` — lands next.)
"""

from __future__ import annotations

import json

from gwbase import Orchestrator, ServiceSettings
from gwbase.transport_encoding import RoutingEnvelope, TransportClass

from gnr.db.authority import AuthoritySource, PostgresAuthority
from gnr.db.validate import parent_alias
from gnr.sema.codec import default_codec
from gnr.sema.property_format import LeftRightDot
from gnr.sema.types import GNodeForest

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
            # Channel = the alias the audience is bound to. For a re-parent that
            # introduces N, that is N's parent E — the deepest ancestor whose alias
            # is STABLE across the change, and a proper prefix of every moved
            # node's OLD alias (so every affected listener's ancestor-binding set
            # includes it). Keying on N's NEW alias would reach nobody: listeners
            # bind prefixes of the aliases they knew.
            self.broadcast_topology(broadcast, radio_channel=parent_alias(cmd.new_node.alias))

    def broadcast_snapshot(self, root: LeftRightDot) -> None:
        """Broadcast the current forest under `root` on `radio_channel = root`.

        The snapshot case of the channel rule: nothing changed, so the audience-
        known alias IS the current alias. Listeners treat it identically to a
        change broadcast (upsert the subtree) — it is the anti-entropy /
        bootstrap-refresh path. Cadence is the deployment's concern (a periodic
        driver calls this per top-level root); the mechanism lives here.
        """
        self.broadcast_topology(self.authority.get_forest([root]), radio_channel=root)

    def broadcast_topology(self, broadcast: GNodeForest, *, radio_channel: LeftRightDot) -> None:
        """Publish the affected forest on the registry's mic exchange (best-effort),
        keyed on `radio_channel` — the audience-known alias of what changed (dots
        preserved: the channel is the multi-segment tail of the `rjb` key, which is
        what lets listeners bind by alias hierarchy)."""
        self.send(
            envelope=self.broadcast_envelope(
                type_name=broadcast.type_name, radio_channel=radio_channel
            ),
            body=json.dumps(broadcast.to_dict()).encode(),
        )
