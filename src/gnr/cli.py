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


def main() -> None:
    parser = argparse.ArgumentParser(prog="gnr", description="Grid Node Registry service")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rabbit", help="run the rabbit write loop")
    sub.add_parser("api", help="run the HTTP read façade")
    args = parser.parse_args()
    if args.command == "rabbit":
        _run_rabbit()
    else:
        _run_api()
