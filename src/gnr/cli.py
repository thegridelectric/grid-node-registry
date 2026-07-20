"""Service entry points — the `gnr` console script.

`gnr rabbit` runs the write loop (commands in, forest broadcasts out);
`gnr api` runs the HTTP read façade; `gnr snapshot` broadcasts each forest
root once and exits — the anti-entropy path, driven by a systemd timer on
the box (`service/gnr-snapshot.timer`; the cadence lives in the timer file).
"""

import argparse
import time

import uvicorn

from gnr.db.models import GNodeSql
from gnr.db.session import SessionLocal
from gnr.db.validate import is_forest_root
from gnr.gnr_rabbit import GnrRabbit
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
    args = parser.parse_args()
    if args.command == "rabbit":
        _run_rabbit()
    elif args.command == "api":
        _run_api()
    else:
        _run_snapshot(args.roots)
