"""API entrypoint with request-template logging instead of raw URL access logs."""

import logging

import uvicorn


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("claims.http").setLevel(logging.INFO)
    uvicorn.run("api.main:create_app", factory=True, host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()
