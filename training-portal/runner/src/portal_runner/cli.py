from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from .config import RunnerConfig
from .worker import Runner


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "datasets":
        from .datasets import main as datasets_main

        return datasets_main(argv[1:])
    parser = argparse.ArgumentParser(description="Run fixed YOLOv9-s portal jobs")
    parser.add_argument(
        "--once",
        action="store_true",
        help="claim at most one job and exit; useful for smoke checks",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        config = RunnerConfig.from_env()
    except ValueError as exc:
        parser.error(str(exc))

    stop_event = threading.Event()
    runner = Runner(config, stop_event=stop_event)
    previous_handlers = {}

    def stop(signum, _frame):
        logging.getLogger("portal_runner").info(
            "received signal %s; stopping after bounded child shutdown", signum
        )
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, stop)
    try:
        runner.serve(once=args.once)
        return 0
    except Exception:
        logging.getLogger("portal_runner").exception("runner stopped with an error")
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
