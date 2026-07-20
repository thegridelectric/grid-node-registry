"""Service entry points — the `gnr` console script.

`gnr rabbit` runs the write loop (commands in, forest broadcasts out);
`gnr api` runs the HTTP read façade.
"""

import argparse

import uvicorn

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


def _run_rebuild(path: str, wipe: bool) -> None:
    from gnr.db.models import (
        AliasAssignmentSql,
        CommandLogSql,
        ConnectivityEdgeSql,
        GNodeSql,
        PositionPointSql,
    )
    from gnr.db.session import SessionLocal
    from gnr.db.validate import validate_registry
    from gnr.rebuild import rebuild_from_file
    from gnr.settings import Settings

    universe = Settings().universe
    with SessionLocal() as s:
        occupied = s.query(GNodeSql).count()
        if occupied and not wipe:
            raise SystemExit(
                f"registry holds {occupied} GNodes; rerun with --wipe to rebuild from capture"
            )
        if wipe:
            # command_log must go too: idempotent replay short-circuits on a
            # logged hash, which would skip re-applying against wiped state.
            for table in (
                ConnectivityEdgeSql,
                AliasAssignmentSql,
                GNodeSql,
                PositionPointSql,
                CommandLogSql,
            ):
                s.query(table).delete(synchronize_session=False)
            s.commit()

    report = rebuild_from_file(path)
    with SessionLocal() as s:
        violations = validate_registry(s, universe)

    print(
        f"applied {report.applied}, re-refused {report.refused}, "
        f"checkpoints {report.checkpoints}"
    )
    if report.skipped_type_names:
        print("skipped:", ", ".join(sorted(report.skipped_type_names)))
    for m in report.mismatches:
        print("MISMATCH:", m)
    for v in violations:
        print("VIOLATION:", v)
    if report.mismatches or violations:
        raise SystemExit(1)
    print("rebuild ok")


def main() -> None:
    parser = argparse.ArgumentParser(prog="gnr", description="Grid Node Registry service")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rabbit", help="run the rabbit write loop")
    sub.add_parser("api", help="run the HTTP read façade")
    rebuild = sub.add_parser(
        "rebuild", help="rebuild the registry from a JSONL capture (the restore path)"
    )
    rebuild.add_argument("capture", help="path to the capture file (JSON Lines)")
    rebuild.add_argument(
        "--wipe", action="store_true",
        help="empty the registry first (required when it holds rows)",
    )
    args = parser.parse_args()
    if args.command == "rabbit":
        _run_rabbit()
    elif args.command == "api":
        _run_api()
    else:
        _run_rebuild(args.capture, wipe=args.wipe)
