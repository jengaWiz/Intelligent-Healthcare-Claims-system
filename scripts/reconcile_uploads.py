"""Report orphan counts by default; --apply removes only unreferenced generated files."""

import argparse
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import Settings
from services.upload_reconciliation import reconcile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        settings = Settings()
        timeout = settings.database_timeout_seconds
        engine = create_engine(
            settings.require_database_url(),
            hide_parameters=True,
            pool_timeout=timeout,
            connect_args={
                "connect_timeout": timeout,
                "options": f"-c statement_timeout={timeout * 1000}",
            },
        )
        with sessionmaker(bind=engine).begin() as db:
            result = reconcile(db, settings.upload_dir, apply=args.apply)
        print(json.dumps(result, sort_keys=True))
        return 1 if result["missing"] else 0
    except Exception:
        print('{"code":"reconciliation_unavailable"}')
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
