"""Rebuild-from-capture over a real broker — THE durability EDD experiment.

The spoke's done-when: capture a genesis + mutation stream with a real ear
tap, wipe the registry, rebuild from the capture file alone, and land in an
equivalent validate-clean registry with the captured broadcasts matching
(executor *Durability*: "capture → wipe → replay → `validate_registry`-clean,
forests matching the captured broadcasts"). The tap is a bare `ActorBase` —
gwbase's default IS an ear tap — appending every message it hears to a JSONL
file, no decoding: the same shape OPS-443's durable capture writes.
"""

from __future__ import annotations

import time

import pytest
from gwbase import ActorBase, Orchestrator, ServiceSettings
from gwbase.config.rabbit_settings import RabbitBrokerClient
from gwbase.topology import EAR_EXCHANGE
from gwbase.transport_encoding import RoutingEnvelope, TransportClass
from pydantic import SecretStr
from test_layer2_rabbit import provision_topology
from test_rebuild import _pending, _wipe

from gnr.db.authority import PostgresAuthority
from gnr.db.validate import validate_registry
from gnr.gnr_rabbit import GnrRabbit
from gnr.rebuild import LocalCaptureDir, checkpoint_state, rebuild
from gnr.sema.enums import BaseGNodeClass as B
from gnr.sema.types import GNodeCreateCmd, GNodeReparentCmd

pytestmark = pytest.mark.integration

REGISTRY_ALIAS = "d1.registry"


class CaptureTap(ActorBase):
    """A real ear tap: store every message heard on the bus as one object
    under the ear's name grammar (`<from>-<type>-<ms>-<source>.json`), body
    verbatim. `dispatch_message` (the raw tier) rather than a decoded hook —
    a lossless tap does not interpret; capture order is arrival order."""

    def __init__(self, *, settings: ServiceSettings, root) -> None:
        super().__init__(settings=settings)
        self._root = root

    def local_rabbit_startup(self) -> None:
        # The tap's slice is everything: the fabric feeds the bus into
        # `ear_tx`; a deployed capture may narrow this binding to its slice.
        self._single_channel.queue_bind(self.queue_name, EAR_EXCHANGE, routing_key="#")

    def dispatch_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        name = (
            f"{envelope.from_alias}-{envelope.type_name}"
            f"-{int(time.time() * 1000)}-{self.alias}.json"
        )
        (self._root / name).write_bytes(body)


class CommandPublisher(Orchestrator):
    """A MarketMaker-class publisher: sends commands to the registry, hears
    nothing back (the tap does the witnessing)."""

    def __init__(self, *, settings: ServiceSettings, registry_alias: str) -> None:
        super().__init__(
            settings=settings,
            transport_class=TransportClass.MarketMaker,
            my_super_alias="d1.super1",
            my_time_coordinator_alias="d1.time",
        )
        self._registry_alias = registry_alias

    def process_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        pass  # publisher only; the tap does the witnessing

    def publish(self, cmd) -> None:
        self.send(
            envelope=self.direct_envelope(
                type_name=cmd.type_name,
                to_class=TransportClass.GridNodeRegistry,
                to_alias=self._registry_alias,
            ),
            body=cmd.to_bytes(),
        )


def _wait_for(predicate, timeout_s: float, message: str) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise TimeoutError(f"Timed out after {timeout_s}s waiting for: {message}")


def _forest_objects(root) -> int:
    return sum(1 for p in root.glob("*.json") if "-g.node.forest-" in p.name)


def test_rebuild_from_real_broker_capture(session_factory, rabbit_url, tmp_path):
    _wipe(session_factory)
    provision_topology(rabbit_url)
    rabbit = RabbitBrokerClient(url=SecretStr(rabbit_url))
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()

    registry = GnrRabbit(
        settings=ServiceSettings(service_alias=REGISTRY_ALIAS, rabbit=rabbit),
        authority=PostgresAuthority(session_factory=session_factory, universe="d1"),
    )
    tap = CaptureTap(
        settings=ServiceSettings(service_alias="d1.captap", rabbit=rabbit),
        root=capture_dir,
    )
    mm = CommandPublisher(
        settings=ServiceSettings(service_alias="d1.isone", rabbit=rabbit),
        registry_alias=REGISTRY_ALIAS,
    )
    tap.start()
    registry.start()
    mm.start()
    try:
        _wait_for(lambda: tap._consuming, 15, "tap is consuming")
        _wait_for(lambda: registry._consuming, 15, "registry is consuming")
        _wait_for(lambda: mm._consuming, 15, "publisher is consuming")

        # Genesis as commands, parents-first (the fleet-ingest posture), then
        # a re-parent: keene.sub arrives, the willow home moves beneath it.
        isone = _pending("d1.isone", B.MarketMaker)
        keene = _pending("d1.isone.keene", B.ConnectivityNode)
        willow = _pending("d1.isone.keene.willow", B.LeafTransactiveNode)
        for node in (isone, keene, willow):
            mm.publish(GNodeCreateCmd(new_node=node))
        _wait_for(
            lambda: _forest_objects(capture_dir) >= 3,
            20,
            "3 create broadcasts captured",
        )

        sub = _pending("d1.isone.keene.sub", B.ConnectivityNode)
        mm.publish(
            GNodeReparentCmd(new_node=sub, moved_child_g_node_ids=[willow.g_node_id])
        )
        _wait_for(
            lambda: _forest_objects(capture_dir) >= 4,
            20,
            "re-parent broadcast captured",
        )
    finally:
        mm.stop()
        registry.stop()
        tap.stop()

    auth = PostgresAuthority(session_factory=session_factory, universe="d1")
    original = auth.get_forest(["d1.isone"]).to_dict()
    assert any(g["Alias"] == "d1.isone.keene.sub.willow" for g in original["Nodes"])

    # Wipe everything; the capture file is now the only record. Rebuild.
    _wipe(session_factory)
    report = rebuild(LocalCaptureDir(capture_dir), auth)

    assert report.ok, report.mismatches
    assert report.applied == 4
    assert report.refused == 0
    assert report.checkpoints == 4
    assert checkpoint_state(
        auth.get_forest(["d1.isone"]).to_dict()
    ) == checkpoint_state(original)
    with session_factory() as s:
        assert validate_registry(s, "d1") == []
