"""Rabbit transport adapter — a thin gwbase actor over the `AuthoritySource` core.

One of the design's two thin adapters (the other is the FastAPI façade): it maps
rabbit messages onto the transport-agnostic `AuthoritySource` handlers and back,
and holds **no** registry logic of its own. The registry is a gwbase
`TransportClass.GridNodeRegistry` (a routing identity) — deliberately NOT a Sema
enum, since transport routing is decoupled from message decoding.

The write loop: consume a `g.node.create.cmd` or `g.node.reparent.cmd`, apply
it, and broadcast the resulting `g.node.forest` (the affected subtree).

The snapshot loop: a thread inside the same process broadcasts the forest
under every root once per `snapshot_interval_s` (anti-entropy). One process
holds the registry's cert: the FIS gate leases a cert's identity to one
running instance, so a second process presenting it would supersede this one.
"""

from __future__ import annotations

import json
import threading

from gwbase import Orchestrator, ServiceSettings
from gwbase.transport_encoding import RoutingEnvelope, TransportClass

from gnr.db.authority import (
    AuthoritySource,
    CreateError,
    PostgresAuthority,
    ReparentError,
)
from gnr.db.validate import is_forest_root, parent_alias
from gnr.ids import command_hash
from gnr.sema.codec import default_codec
from gnr.sema.property_format import LeftRightDot
from gnr.sema.types import GNodeCmdAck, GNodeCmdNack, GNodeForest
from gnr.settings import Settings

CREATE_CMD = "g.node.create.cmd"
REPARENT_CMD = "g.node.reparent.cmd"
# The first snapshot waits this long after start, so a restart (or a crash
# loop) does not re-broadcast the forest at once.
SNAPSHOT_STARTUP_DELAY_S = 300


class GnrRabbit(Orchestrator):
    """The registry as a rabbit actor: consumes commands, broadcasts topology."""

    def __init__(
        self,
        *,
        settings: ServiceSettings,
        snapshot_interval_s: float,
        snapshot_startup_delay_s: float,
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
        self.authority: AuthoritySource = authority or PostgresAuthority(
            universe=Settings().universe,
            write_proof_sha256=Settings().write_proof_sha256,
        )
        # One lock around read-then-broadcast on both paths, so a snapshot
        # read before a write commits is never published after that write's
        # change broadcast (publishes are queued onto the ioloop in order).
        self.forest_lock = threading.Lock()
        self.snapshot_interval_s = snapshot_interval_s
        self.snapshot_startup_delay_s = snapshot_startup_delay_s
        self.snapshot_stop = threading.Event()
        self.snapshot_thread = threading.Thread(
            target=self.run_snapshots, name=f"{self.alias}-snapshots", daemon=True
        )

    def local_start(self) -> None:
        super().local_start()
        self.snapshot_thread.start()

    def local_stop(self) -> None:
        super().local_stop()
        self.snapshot_stop.set()
        if self.snapshot_thread.is_alive():
            self.snapshot_thread.join()

    def process_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        if envelope.type_name not in (CREATE_CMD, REPARENT_CMD):
            return
        # Correlation is the hash of the bytes AS PUBLISHED — the same bytes
        # the sender can hash on its side, and the same content-address the
        # command log records for an applied command.
        chash = command_hash(body)
        cmd = default_codec.from_dict(json.loads(body))
        with self.forest_lock:
            self.apply_and_broadcast(envelope, cmd, chash)

    def apply_and_broadcast(self, envelope: RoutingEnvelope, cmd, chash: str) -> None:
        try:
            if envelope.type_name == CREATE_CMD:
                broadcast = self.authority.apply_create(cmd)
                # Channel rule for a create: the audience that can already be
                # bound is under the PARENT's alias (nobody binds an alias that
                # didn't exist); a forest-root create has no parent, so its own
                # alias is the only channel there is.
                alias = cmd.new_node.alias
                channel = alias if is_forest_root(alias) else parent_alias(alias)
            else:
                broadcast = self.authority.apply_reparent(cmd)
                # Channel = the alias the audience is bound to. For a re-parent
                # that introduces N, that is N's parent E — the deepest ancestor
                # whose alias is STABLE across the change, and a proper prefix
                # of every moved node's OLD alias (so every affected listener's
                # ancestor-binding set includes it). Keying on N's NEW alias
                # would reach nobody: listeners bind prefixes of aliases they
                # knew.
                channel = parent_alias(cmd.new_node.alias)
        except (CreateError, ReparentError) as e:
            # A refusal is an ANSWER, not an exception to die on: the consume
            # loop survives (an escaped exception here tears down the channel),
            # the sender gets the typed verdict with the reason, and — because
            # the nack rides the bus — the ear captures the refusal as a
            # first-class audit record.
            self._reply(envelope, GNodeCmdNack(command_hash=chash, reason=str(e)))
            return
        self.broadcast_topology(broadcast, radio_channel=channel)
        self._reply(envelope, GNodeCmdAck(command_hash=chash))

    def _reply(self, envelope: RoutingEnvelope, verdict) -> None:
        """The typed verdict (ack/nack), direct to the command's sender."""
        from_class = envelope.from_class
        if from_class is None:
            return  # unknown sender class token — nowhere to address the reply
        self.send(
            envelope=self.direct_envelope(
                type_name=verdict.type_name,
                to_class=from_class,
                to_alias=envelope.from_alias,
            ),
            body=verdict.to_bytes(),
        )

    def run_snapshots(self) -> None:
        """The snapshot loop: one `broadcast_all_snapshots` per interval, the
        first after the startup delay. A tick while not consuming is skipped;
        a tick that raises is logged and the loop keeps going."""
        if self.snapshot_stop.wait(self.snapshot_startup_delay_s):
            return
        while True:
            if self.consuming:
                try:
                    self.broadcast_all_snapshots()
                except Exception:  # the snapshot loop keeps running
                    self.logger.exception("snapshot broadcast failed")
            if self.snapshot_stop.wait(self.snapshot_interval_s):
                return

    def broadcast_all_snapshots(self) -> None:
        """One snapshot per forest root, under the forest lock."""
        for root in self.authority.forest_roots():
            with self.forest_lock:
                self.broadcast_snapshot(root)
            self.logger.info("snapshot broadcast: %s", root)

    def broadcast_snapshot(self, root: LeftRightDot) -> None:
        """Broadcast the current forest under `root` on `radio_channel = root`.

        The snapshot case of the channel rule: nothing changed, so the audience-
        known alias IS the current alias. Listeners treat it identically to a
        change broadcast (upsert the subtree) — it is the anti-entropy /
        bootstrap-refresh path.
        """
        self.broadcast_topology(self.authority.get_forest([root]), radio_channel=root)

    def broadcast_topology(
        self, broadcast: GNodeForest, *, radio_channel: LeftRightDot
    ) -> None:
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
