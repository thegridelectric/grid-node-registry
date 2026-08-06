"""Layer 2 — the rabbit adapter over a real broker (the EDD experiment).

Boots `GnrRabbit` (the registry's gwbase actor) and a MarketMaker stub on a real
RabbitMQ, seeds the `d1` dev universe into a real Postgres, and proves the whole
step-5 write loop end to end: a MarketMaker publishes a `g.node.reparent.cmd`,
the fabric forwards it to the registry's `gnr_tx`, the registry applies the atomic
recursive re-parent, and its `g.node.topology.broadcast` comes back to a real
subscriber **and** the DB reflects the rewrite. This is the experiment that moves
the harness spoke toward Verified — mocks pass where the real broker + atomic
subtree rewrite fail.
"""

from __future__ import annotations

import json
import uuid

import pika
import pytest
from gwbase import topology
from gwbase.config import ServiceSettings
from gwbase.config.rabbit_settings import RabbitBrokerClient
from gwbase.orchestrator import Orchestrator
from gwbase.transport_encoding import RoutingEnvelope, TransportClass
from pydantic import SecretStr

from gnr.db.authority import PostgresAuthority
from gnr.dev_universe import DEV_POSITION_ID, seed_dev_universe
from gnr.gnr_rabbit import GnrRabbit
from gnr.sema.codec import default_codec
from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.types import GNodeForest, GNodeGt, GNodeReparentCmd

pytestmark = pytest.mark.integration

REGISTRY_ALIAS = "d1.gnr"
KEENE = "d1.isone.me.versant.keene"  # a MarketMaker — authority over the beech subtree
BEECH_LTN = f"{KEENE}.beech"
TOPOLOGY_BROADCAST = "g.node.forest"


def provision_topology(url: str) -> None:
    """Declare the gwbase broker fabric (exchanges + bindings) before any actor
    starts — actors only *passively* assert their consume exchange exists. Same
    `gwbase.topology` source the dev/prod definitions are generated from."""
    conn = pika.BlockingConnection(pika.URLParameters(url))
    try:
        ch = conn.channel()
        for ex in topology.exchanges():
            ch.exchange_declare(
                exchange=ex.name,
                exchange_type=ex.exchange_type,
                durable=ex.durable,
                internal=ex.internal,
            )
        for b in topology.exchange_bindings():
            ch.exchange_bind(
                destination=b.destination, source=b.source, routing_key=b.routing_key
            )
    finally:
        conn.close()


class MarketMakerStub(Orchestrator):
    """A MarketMaker that sends the re-parent command and records the registry's
    forest broadcast — subscriber-bound to `gnrmic_tx` on its OWN alias as the
    radio channel (keene is the stable parent under which the re-parent happens,
    so it is the audience-known channel the registry broadcasts on)."""

    def __init__(self, *, settings: ServiceSettings, registry_alias: str) -> None:
        super().__init__(
            settings=settings,
            transport_class=TransportClass.MarketMaker,
            my_super_alias="d1.super1",
            my_time_coordinator_alias="d1.time",
        )
        self._registry_alias = registry_alias
        self.broadcasts: list[bytes] = []
        self.broadcast_channels: list[str | None] = []

    def local_rabbit_startup(self) -> None:
        # Exact-match channel binding: an un-channeled binding would NOT match a
        # channeled key, so receiving anything proves the radio_channel path.
        self.subscribe_broadcast(
            from_alias=self._registry_alias,
            from_class=TransportClass.GridNodeRegistry,
            type_name=TOPOLOGY_BROADCAST,
            radio_channel=KEENE,
        )

    def process_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        if envelope.type_name == TOPOLOGY_BROADCAST:
            self.broadcasts.append(body)
            self.broadcast_channels.append(getattr(envelope, "radio_channel", None))


def _wait_for(predicate, timeout_s: float, message: str, interval_s: float = 0.1):
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval_s)
    raise TimeoutError(f"Timed out after {timeout_s}s waiting for: {message}")


def test_reparent_over_real_broker(session_factory, rabbit_url):
    # Seed the dev universe into the real Postgres.
    with session_factory() as s:
        gnodes = seed_dev_universe(s)
    by_alias = {g.alias: g for g in gnodes}
    beech_ltn = by_alias[BEECH_LTN]

    # Provision the fabric before any actor starts.
    provision_topology(rabbit_url)
    rabbit = RabbitBrokerClient(url=SecretStr(rabbit_url))

    registry = GnrRabbit(
        settings=ServiceSettings(service_alias=REGISTRY_ALIAS, rabbit=rabbit),
        authority=PostgresAuthority(session_factory=session_factory, universe="d1"),
    )
    mm = MarketMakerStub(
        settings=ServiceSettings(service_alias=KEENE, rabbit=rabbit),
        registry_alias=REGISTRY_ALIAS,
    )
    registry.start()
    mm.start()
    try:
        _wait_for(lambda: registry._consuming, 15, "registry is consuming")
        _wait_for(lambda: mm._consuming, 15, "marketmaker is consuming")

        # Introduce a new ConnectivityNode under keene and move the beech home
        # beneath it — the whole beech subtree re-parents atomically.
        new_cn = GNodeGt(
            g_node_id=str(uuid.uuid4()),
            alias=f"{KEENE}.sub",
            base_class=BaseGNodeClass.ConnectivityNode,
            g_node_class="ConnectivityNode",
            status=GNodeStatus.Active,
            position_point_id=DEV_POSITION_ID,
            display_name="sub",
        )
        cmd = GNodeReparentCmd(
            new_node=new_cn, moved_child_g_node_ids=[beech_ltn.g_node_id]
        )

        mm.send(
            envelope=mm.direct_envelope(
                type_name=cmd.type_name,
                to_class=TransportClass.GridNodeRegistry,
                to_alias=REGISTRY_ALIAS,
            ),
            body=cmd.to_bytes(),
        )

        # The broadcast comes back to a real subscriber over the real broker.
        _wait_for(lambda: len(mm.broadcasts) > 0, 15, "topology broadcast received")

        # Snapshot leg: nothing changed since, so the channel is the CURRENT
        # alias — the same keene binding hears it (the anti-entropy path).
        registry.broadcast_snapshot(KEENE)
        _wait_for(lambda: len(mm.broadcasts) > 1, 15, "snapshot broadcast received")
    finally:
        mm.stop()
        registry.stop()

    # The broadcast arrived on the audience-known channel (keene — the stable
    # parent), carrying the rewritten beech subtree.
    assert mm.broadcast_channels[0] == KEENE
    decoded = default_codec.from_dict(json.loads(mm.broadcasts[0]))
    assert isinstance(decoded, GNodeForest)
    broadcast_aliases = {g.alias for g in decoded.nodes}
    assert f"{KEENE}.sub" in broadcast_aliases
    assert f"{KEENE}.sub.beech" in broadcast_aliases
    assert f"{KEENE}.sub.beech.scada" in broadcast_aliases
    assert f"{KEENE}.sub.beech.ta" in broadcast_aliases

    # The snapshot arrived on keene's current alias and carries the whole
    # subtree in its post-rename form.
    assert mm.broadcast_channels[1] == KEENE
    snapshot = default_codec.from_dict(json.loads(mm.broadcasts[1]))
    assert isinstance(snapshot, GNodeForest)
    assert snapshot.roots == [KEENE]
    snap_aliases = {g.alias for g in snapshot.nodes}
    assert KEENE in snap_aliases
    assert f"{KEENE}.sub.beech" in snap_aliases  # the renamed home, current form

    # The DB reflects the rewrite: ids stable, aliases moved, old freed.
    auth = PostgresAuthority(session_factory=session_factory, universe="d1")
    assert auth.get_by_alias(BEECH_LTN) is None
    moved = auth.get_by_alias(f"{KEENE}.sub.beech")
    assert moved is not None and moved.g_node_id == beech_ltn.g_node_id
    assert auth.get_by_alias(f"{KEENE}.sub.beech.scada") is not None
    assert auth.get_by_alias(f"{KEENE}.sub.beech.ta") is not None
