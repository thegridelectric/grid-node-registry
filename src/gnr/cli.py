"""Service entry points — the `gnr` console script.

`gnr rabbit` runs the write loop (commands in, forest broadcasts out);
`gnr api` runs the HTTP read façade; `gnr snapshot` broadcasts each forest
root once and exits — the anti-entropy path, driven by a systemd timer on
the box (`service/gnr-snapshot.timer`; the cadence lives in the timer file).

`gnr create` is the operator surface for entering ONE GNode: checks the
alias isn't taken (via the read API), builds the node **Pending** with a
staged position, confirms, and publishes the `g.node.create.cmd` over the
broker with the write Proof (env `GNR_WRITE_PROOF` or an interactive prompt
— never a CLI argument). Operator env: `GNR_RABBIT__URL` (the broker),
`GNR_API_BASE` (default `http://127.0.0.1:8000`), and `SSL_CERT_FILE`
pointing at the GridWorks CA when the broker's cert chains to it.
"""

import argparse
import getpass
import json
import os
import sys
import time
import urllib.request
import uuid

import uvicorn
from pydantic import SecretStr

from gwbase import Orchestrator, ServiceSettings
from gwbase.config.rabbit_settings import RabbitBrokerClient
from gwbase.transport_encoding import RoutingEnvelope, TransportClass

from gnr.db.models import GNodeSql
from gnr.db.session import SessionLocal
from gnr.db.validate import is_forest_root, universe_of
from gnr.gnr_rabbit import GnrRabbit
from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.types import GNodeCreateCmd, GNodeGt
from gnr.settings import ApiRunSettings, RabbitRunSettings


def _run_rabbit() -> None:
    run = RabbitRunSettings()
    actor = GnrRabbit(
        settings=run,
        my_super_alias=run.super_alias,
        my_time_coordinator_alias=run.time_coordinator_alias,
    )
    actor.start()
    try:
        actor.consuming_thread.join()
    except KeyboardInterrupt:
        actor.stop()


def _run_api() -> None:
    run = ApiRunSettings()
    uvicorn.run("gnr.api:app", host=run.api_host, port=run.api_port)


def _run_snapshot(roots: list[str]) -> None:
    if not roots:
        with SessionLocal() as s:
            roots = sorted(
                row.alias for row in s.query(GNodeSql).all() if is_forest_root(row.alias)
            )
    run = RabbitRunSettings()
    actor = GnrRabbit(
        settings=run,
        my_super_alias=run.super_alias,
        my_time_coordinator_alias=run.time_coordinator_alias,
    )
    actor.start()
    deadline = time.time() + 15
    while not actor._consuming and time.time() < deadline:
        time.sleep(0.1)
    try:
        for root in roots:
            actor.broadcast_snapshot(root)
            print(f"snapshot broadcast: {root}")
    finally:
        actor.stop()


class _OperatorPublisher(Orchestrator):
    """MarketMaker-class publisher for operator commands; hears nothing back
    (verification rides the read API)."""

    def __init__(self, *, settings: ServiceSettings, universe: str) -> None:
        super().__init__(
            settings=settings,
            transport_class=TransportClass.MarketMaker,
            my_super_alias=f"{universe}.super",
            my_time_coordinator_alias=f"{universe}.time",
        )

    def process_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        pass


def _api_get(base: str, alias: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base}/gnr/g-node-by-alias/{alias}", timeout=5) as r:
            return json.load(r)
    except Exception:
        return None


def _run_create(args: argparse.Namespace) -> None:
    api = os.environ.get("GNR_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    universe = universe_of(args.alias)

    existing = _api_get(api, args.alias)
    if existing is not None:
        sys.exit(
            f"{args.alias} already exists: {existing['GNodeId']} "
            f"({existing['Status']}) — nothing to do"
        )

    base_class = BaseGNodeClass(args.base_class)
    node = GNodeGt(
        g_node_id=args.g_node_id or str(uuid.uuid4()),
        alias=args.alias,
        base_class=base_class,
        g_node_class=args.g_node_class or base_class.value,
        status=GNodeStatus.Pending,
        position_point_id=(
            None if base_class == BaseGNodeClass.Logical else str(uuid.uuid4())
        ),
        display_name=args.display_name or args.alias.rsplit(".", 1)[-1].title(),
    )
    print(json.dumps(node.to_dict(), indent=2))
    if input("ENTER to publish this create (anything else aborts) ... ").strip():
        sys.exit("aborted")

    proof = os.environ.get("GNR_WRITE_PROOF") or getpass.getpass("Write Proof: ")
    url = os.environ.get("GNR_RABBIT__URL")
    if not url:
        sys.exit("set GNR_RABBIT__URL for the target broker")
    pub = _OperatorPublisher(
        settings=ServiceSettings(
            service_alias=f"{universe}.registrar",
            rabbit=RabbitBrokerClient(url=SecretStr(url)),
        ),
        universe=universe,
    )
    pub.start()
    deadline = time.time() + 20
    while not pub._consuming and time.time() < deadline:
        time.sleep(0.2)
    if not pub._consuming:
        sys.exit("could not reach the broker")
    try:
        cmd = GNodeCreateCmd(new_node=node, proof=proof or None)
        pub.send(
            envelope=pub.direct_envelope(
                type_name=cmd.type_name,
                to_class=TransportClass.GridNodeRegistry,
                to_alias=f"{universe}.registry",
            ),
            body=cmd.to_bytes(),
        )
        for _ in range(40):
            if _api_get(api, node.alias) is not None:
                print(f"✓ {node.alias} is in the registry ({node.g_node_id})")
                return
            time.sleep(0.5)
        sys.exit(
            f"✗ {node.alias} did not appear within 20s — likely a refused "
            "command (bad Proof? parent missing?); check the registry's "
            "gnr-rabbit journal"
        )
    finally:
        pub.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="gnr", description="Grid Node Registry service")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rabbit", help="run the rabbit write loop")
    sub.add_parser("api", help="run the HTTP read façade")
    snapshot = sub.add_parser(
        "snapshot",
        help="broadcast a forest snapshot per root and exit (anti-entropy)",
    )
    snapshot.add_argument(
        "roots", nargs="*",
        help="root aliases to snapshot (default: every forest root)",
    )
    create = sub.add_parser(
        "create",
        help="operator: enter ONE GNode (Pending) over the broker",
    )
    create.add_argument("alias", help="e.g. hw1.isone.me.versant.keene")
    create.add_argument(
        "base_class",
        choices=[c.value for c in BaseGNodeClass],
        help="the node's BaseGNodeClass",
    )
    create.add_argument(
        "--g-node-id",
        help="use this GNodeId (e.g. a layout's); default: mint a fresh one",
    )
    create.add_argument(
        "--g-node-class",
        help="when it differs from the base class (e.g. Scada for Logical)",
    )
    create.add_argument("--display-name")
    args = parser.parse_args()
    if args.command == "rabbit":
        _run_rabbit()
    elif args.command == "api":
        _run_api()
    elif args.command == "snapshot":
        _run_snapshot(args.roots)
    else:
        _run_create(args)
