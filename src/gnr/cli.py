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
import ssl
import sys
import time
import urllib.request
import uuid

import certifi
import uvicorn

from gwbase import Orchestrator, ServiceSettings
from gwbase.transport_encoding import RoutingEnvelope, TransportClass

from gnr.db.models import GNodeSql
from gnr.db.session import SessionLocal
from gnr.db.validate import is_forest_root, universe_of
from gnr.gnr_rabbit import GnrRabbit
from gnr.ids import command_hash
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
    """MarketMaker-class publisher for operator commands. The registry
    replies with a typed verdict (`g.node.cmd.ack` / `g.node.cmd.nack`)
    direct to this alias; verdicts land in `self.verdicts` keyed by the
    command's content hash."""

    def __init__(self, *, settings: ServiceSettings, universe: str) -> None:
        super().__init__(
            settings=settings,
            transport_class=TransportClass.MarketMaker,
            my_super_alias=f"{universe}.super",
            my_time_coordinator_alias=f"{universe}.time",
        )
        self.verdicts: dict[str, dict] = {}

    def process_message(self, *, envelope: RoutingEnvelope, body: bytes) -> None:
        if envelope.type_name in ("g.node.cmd.ack", "g.node.cmd.nack"):
            verdict = json.loads(body)
            self.verdicts[verdict["CommandHash"]] = verdict


def _api_get(base: str, alias: str) -> dict | None:
    # Pin the public-CA bundle explicitly: the operator env sets SSL_CERT_FILE
    # to the GridWorks CA for the BROKER handshake, which would otherwise
    # replace the default bundle and break verification of the API's
    # publicly-issued cert.
    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(
            f"{base}/gnr/g-node-by-alias/{alias}", timeout=5, context=ctx
        ) as r:
            return json.load(r)
    except Exception:
        return None


_PHYSICAL = [c.value for c in BaseGNodeClass if c != BaseGNodeClass.Logical]
_KNOWN_LOGICAL = [
    "Scada", "TimeCoordinator", "WeatherForecastService", "PriceForecastService",
]


def _infer_base(g_node_class: str) -> BaseGNodeClass:
    """g.node.gt axiom 1, mechanically: a GNodeClass equal to a physical
    BaseGNodeClass value has that base; any other string is Logical."""
    if g_node_class in _PHYSICAL:
        return BaseGNodeClass(g_node_class)
    return BaseGNodeClass.Logical


def _create_wizard(args: argparse.Namespace) -> None:
    """Fill the create args interactively: GNodeClass menu → inferred base →
    alias → display name → GNodeId."""
    options = _PHYSICAL + _KNOWN_LOGICAL + ["other Logical (type it)"]
    print("GNodeClass:")
    for i, opt in enumerate(options, 1):
        print(f"  {i:2}. {opt}")
    while True:
        raw = input(f"choose [1-{len(options)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            break
    picked = options[int(raw) - 1]
    if picked.startswith("other"):
        picked = input("GNodeClass (namespaced string, no whitespace): ").strip()
    args.g_node_class = picked
    base = _infer_base(picked)
    args.base_class = base.value
    print(f"  BaseGNodeClass (inferred, g.node.gt axiom 1): {base.value}")

    args.alias = input("alias (left.right.dot, e.g. hw1.isone.me): ").strip()
    tail = args.alias.rsplit(".", 1)[-1].title()
    args.display_name = input(f"display name [{tail}]: ").strip() or tail
    args.g_node_id = input("GNodeId [ENTER to mint fresh]: ").strip() or None


def _run_create(args: argparse.Namespace) -> None:
    if not args.alias or not args.g_node_class:
        _create_wizard(args)
    elif not args.base_class:
        args.base_class = _infer_base(args.g_node_class).value

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

    proof = os.environ.get("GNR_WRITE_PROOF") or getpass.getpass(
        "Write Proof (empty if the target has no gate): "
    )
    # Broker TLS trust: when the target broker's cert chains to a private CA
    # (GNR_BROKER_CA_FILE), scope the trust override to THIS process only —
    # exporting SSL_CERT_FILE shell-wide poisons every other tool's TLS
    # (pip/uv included: the env var REPLACES the default bundle).
    broker_ca = os.environ.get("GNR_BROKER_CA_FILE")
    if broker_ca:
        os.environ["SSL_CERT_FILE"] = broker_ca
    # Broker connection from the usual settings chain: an exported
    # GNR_RABBIT__URL wins over .env (pydantic env > env_file), so the same
    # command serves the local rehearsal rig and a remote target.
    rabbit = RabbitRunSettings().rabbit
    pub = _OperatorPublisher(
        settings=ServiceSettings(
            service_alias=f"{universe}.gnregistrar",
            rabbit=rabbit,
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
        payload = cmd.to_bytes()
        chash = command_hash(payload)
        pub.send(
            envelope=pub.direct_envelope(
                type_name=cmd.type_name,
                to_class=TransportClass.GridNodeRegistry,
                to_alias=f"{universe}.gnr",
            ),
            body=payload,
        )
        # The registry answers with a typed verdict, correlated by the hash
        # of the bytes we just published.
        verdict = None
        deadline = time.time() + 10
        while verdict is None and time.time() < deadline:
            verdict = pub.verdicts.get(chash)
            time.sleep(0.1)
        if verdict is not None and verdict["TypeName"] == "g.node.cmd.nack":
            sys.exit(f"✗ refused: {verdict['Reason']}")
        if verdict is not None:
            print(f"✓ applied (ack {chash[:12]}…) — confirming visibility …")
        # Visibility proof either way: the node on the same public surface
        # everyone reads. (No verdict after 10s ⇒ an older registry; the poll
        # is then the only signal.)
        for _ in range(40):
            if _api_get(api, node.alias) is not None:
                print(f"✓ {node.alias} is in the registry ({node.g_node_id})")
                return
            time.sleep(0.5)
        sys.exit(
            f"✗ {node.alias} not visible on the read API within 20s — check "
            "the registry's gnr-rabbit journal"
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
        help="operator: enter ONE GNode (Pending) over the broker; no "
             "arguments → interactive wizard",
    )
    create.add_argument(
        "alias", nargs="?",
        help="e.g. hw1.isone.me.versant.keene (omit for the wizard)",
    )
    create.add_argument(
        "g_node_class", nargs="?",
        help="GNodeClass, e.g. MarketMaker or Scada — BaseGNodeClass is "
             "inferred (g.node.gt axiom 1)",
    )
    create.add_argument(
        "--g-node-id",
        help="use this GNodeId (e.g. a layout's); default: mint a fresh one",
    )
    create.add_argument("--display-name")
    create.set_defaults(base_class=None)
    args = parser.parse_args()
    if args.command == "rabbit":
        _run_rabbit()
    elif args.command == "api":
        _run_api()
    elif args.command == "snapshot":
        _run_snapshot(args.roots)
    else:
        _run_create(args)
