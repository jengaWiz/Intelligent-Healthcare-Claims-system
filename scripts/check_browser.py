"""Run an isolated real API/worker browser smoke against a migrated test database."""

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise SystemExit("Set TEST_DATABASE_URL to a dedicated migrated test database")
    with tempfile.TemporaryDirectory(prefix="claims-browser-") as directory:
        origin = "http://127.0.0.1:8047"
        env = {
            **os.environ,
            "DATABASE_URL": url,
            "UPLOAD_DIR": directory,
            "DEMO_PASSWORD": "browser-synthetic-only",
            "API_AUTH_TOKEN": "browser-operator-only",
            "PUBLIC_ORIGIN": origin,
            "SESSION_SECURE": "false",
            "SYNTHETIC_MODE": "true",
            "BROWSER_BASE_URL": origin,
            "BROWSER_PASSWORD": "browser-synthetic-only",
        }
        children = []
        try:
            with open(Path(directory) / "services.log", "w") as logs:
                children.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "api.main:create_app",
                            "--factory",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            "8047",
                            "--no-access-log",
                        ],
                        cwd=root,
                        env=env,
                        stdout=logs,
                        stderr=logs,
                    )
                )
                children.append(
                    subprocess.Popen(
                        [sys.executable, "-m", "worker"],
                        cwd=root,
                        env=env,
                        stdout=logs,
                        stderr=logs,
                    )
                )
                for _ in range(100):
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError("Browser smoke service exited")
                    try:
                        with urllib.request.urlopen(origin + "/health/live", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Browser smoke service did not become live")
                result = subprocess.run(
                    ["npm", "test", "--prefix", "tests/browser"], cwd=root, env=env, timeout=150
                )
                return result.returncode
        finally:
            for child in children:
                child.terminate()
            for child in children:
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            # Remove only the dedicated browser-smoke workspace data.
            from sqlalchemy import create_engine, delete

            from models import BrowserSession, Claim

            engine = create_engine(url, hide_parameters=True)
            with engine.begin() as db:
                db.execute(delete(Claim).where(Claim.source_system == "synthetic-demo-ui"))
                # Test DB only: browser-only sessions use this dedicated launcher.
                db.execute(delete(BrowserSession))
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
