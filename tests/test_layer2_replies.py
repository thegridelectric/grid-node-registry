"""Typed write verdicts over a real broker — ack, nack-with-reason, and the
survival of the consume loop.

Exposed by the first production refusal (2026-07-21): a `CreateError`
escaping `process_message` tore down the registry's consume channel, and the
operator's only signal was a 20-second poll timeout. This experiment proves
the fix end to end: a refused command comes back as a `g.node.cmd.nack`
carrying the registry's reason, the write loop keeps consuming (same
connection), and the next valid command lands with a `g.node.cmd.ack` —
correlation by content hash throughout.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
from pydantic import SecretStr

from gwbase import Orchestrator, ServiceSettings
from gwbase.config.rabbit_settings import RabbitBrokerClient
from gwbase.transport_encoding import RoutingEnvelope, TransportClass

from gnr.db.authority import PostgresAuthority
from gnr.db.models import (
    AliasAssignmentSql,
    CommandLogSql,
    ConnectivityEdgeSql,
    GNodeSql,
    PositionPointSql,
)
from gnr.gnr_rabbit import GnrRabbit
from gnr.ids import command_hash
from gnr.sema.enums import BaseGNodeClass as B, GNodeStatus as S
from gnr.sema.types import GNodeCreateCmd, GNodeGt

from test_layer2_rabbit import provision_topology

pytestmark = pytest.mark.integration

REGISTRY_ALIAS = "d1.gnr"


def _wipe(session_factory):
    with session_factory() as s:
        for table in (
            ConnectivityEdgeSql, AliasAssignmentSql, GNodeSql,
            PositionPointSql, CommandLogSql,
        ):
            s.query(table).delete(synchronize_session=False)
        s.commit()


def _wait_for(predicate, timeout_s: float, message: str) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise TimeoutError(f"Timed out after {timeout_s}s waiting for: {message}")


def _pending_cn(alias: str) -> GNodeGt:
    return GNodeGt(
        g_node_id=str(uuid.uuid4()), alias=alias,
        base_class=B.ConnectivityNode, g_node_class="ConnectivityNode",
        status=S.Pending, position_point_id=str(uuid.uuid4()),
        display_name=alias.rsplit(".", 1)[-1],
    )


class VerdictPublisher(Orchestrator):
    """MarketMaker-class publisher recording the registry's typed verdicts."""

    def __init__(self, *, settings: ServiceSettings, registry_alias: str) -> None:
        super().__init__(
            settings=settings,
            transport_class=TransportClass.MarketMaker,
            my_super_alias="d1.super1",
            my_time_coordinator_alias="d1.time",
        )
        self._registry_alias = registry_alias
        self.verdicts: dict[str, dict] = {}

    def process_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        if envelope.type_name in ("g.node.cmd.ack", "g.node.cmd.nack"):
            v = json.loads(body)
            self.verdicts[v["CommandHash"]] = v

    def publish(self, cmd) -> None:
        self.send(
            envelope=self.direct_envelope(
                type_name=cmd.type_name,
                to_class=TransportClass.GridNodeRegistry,
                to_alias=self._registry_alias,
            ),
            body=cmd.to_bytes(),
        )


def test_nack_with_reason_then_ack_on_same_connection(session_factory, rabbit_url):
    _wipe(session_factory)
    provision_topology(rabbit_url)
    rabbit = RabbitBrokerClient(url=SecretStr(rabbit_url))

    registry = GnrRabbit(
        settings=ServiceSettings(service_alias=REGISTRY_ALIAS, rabbit=rabbit),
        authority=PostgresAuthority(session_factory=session_factory, universe="d1"),
    )
    mm = VerdictPublisher(
        settings=ServiceSettings(service_alias="d1.isone", rabbit=rabbit),
        registry_alias=REGISTRY_ALIAS,
    )
    registry.start()
    mm.start()
    try:
        _wait_for(lambda: registry._consuming, 15, "registry is consuming")
        _wait_for(lambda: mm._consuming, 15, "publisher is consuming")

        # A command the registry must refuse: an orphan (parent not created).
        orphan = GNodeCreateCmd(new_node=_pending_cn("d1.isone.nowhere.orphan"))
        orphan_hash = command_hash(orphan.to_bytes())
        mm.publish(orphan)
        _wait_for(lambda: orphan_hash in mm.verdicts, 15, "nack received")
        nack = mm.verdicts[orphan_hash]
        assert nack["TypeName"] == "g.node.cmd.nack"
        assert "create parents first" in nack["Reason"]

        # The loop SURVIVED the refusal: the same registry instance, same
        # connection, applies the next valid command and acks it.
        root = GNodeCreateCmd(new_node=GNodeGt(
            g_node_id=str(uuid.uuid4()), alias="d1.isone",
            base_class=B.MarketMaker, g_node_class="MarketMaker",
            status=S.Pending, position_point_id=str(uuid.uuid4()),
            display_name="isone",
        ))
        root_hash = command_hash(root.to_bytes())
        mm.publish(root)
        _wait_for(lambda: root_hash in mm.verdicts, 15, "ack received")
        assert mm.verdicts[root_hash]["TypeName"] == "g.node.cmd.ack"
        assert registry.authority.get_by_alias("d1.isone") is not None
    finally:
        mm.stop()
        registry.stop()
