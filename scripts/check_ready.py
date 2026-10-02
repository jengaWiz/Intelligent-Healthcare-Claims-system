"""Container readiness probe; authentication stays inside the process."""

import os
import urllib.request


def main():
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:8000/health/ready",
            headers={"Authorization": "Bearer " + os.environ["API_AUTH_TOKEN"]},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
