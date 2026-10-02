"""Run with: uv run --locked python -m worker [--once]."""

import argparse
import logging
import signal
from threading import Event

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from config.settings import ConfigurationError, Settings
from worker.runtime import run_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Handle at most one eligible job")
    args = parser.parse_args()
    try:
        settings = Settings()
        timeout = settings.database_timeout_seconds
        engine = create_engine(
            settings.require_database_url(),
            pool_pre_ping=True,
            pool_timeout=timeout,
            hide_parameters=True,
            connect_args={
                "connect_timeout": timeout,
                "options": f"-c statement_timeout={timeout * 1000}",
            },
        )
    except Exception:
        print("worker_configuration_invalid")
        return 1
    factory = sessionmaker(bind=engine, autoflush=False)
    from services.extraction_service import run_extraction_pipeline
    from services.synthetic_processor import process_sample

    processor = process_sample if settings.synthetic_mode else run_extraction_pipeline
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    try:
        while not stop.is_set():
            try:
                handled = run_once(factory, settings, processor=processor)
            except (SQLAlchemyError, ConfigurationError):
                logging.error("worker_database_unavailable")
                if args.once:
                    return 1
                stop.wait(settings.worker_poll_seconds)
                continue
            except Exception:
                logging.error("worker_processing_unavailable")
                if args.once:
                    return 1
                stop.wait(settings.worker_poll_seconds)
                continue
            if args.once:
                return 0
            if not handled:
                stop.wait(settings.worker_poll_seconds)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
