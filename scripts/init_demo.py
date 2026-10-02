"""Generate local-only Docker credentials without printing or overwriting them."""

import os
from pathlib import Path
from secrets import token_hex, token_urlsafe

from sqlalchemy.engine import URL


def database_url(password):
    return URL.create(
        "postgresql+psycopg", username="claims", password=password, host="db", database="claims"
    ).render_as_string(hide_password=False)


def main():
    target = Path(".env.docker")
    values = {
        "POSTGRES_PASSWORD": token_hex(24),
        "API_AUTH_TOKEN": token_urlsafe(32),
        "DEMO_PASSWORD": token_urlsafe(24),
        "PUBLIC_ORIGIN": "http://127.0.0.1:8000",
        "SESSION_SECURE": "false",
        "SYNTHETIC_MODE": "true",
        "ALLOWED_ORIGINS": "[]",
        "DEMO_PORT": "8000",
    }
    values["DATABASE_URL"] = database_url(values["POSTGRES_PASSWORD"])
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        prior = dict(
            line.split("=", 1)
            for line in target.read_text().splitlines()
            if line and not line.startswith("#")
        )
        if "DATABASE_URL" not in prior:
            with target.open("a") as stream:
                stream.write("DATABASE_URL=" + database_url(prior["POSTGRES_PASSWORD"]) + "\n")
        print(".env.docker already exists; existing credentials retained")
        return
    with os.fdopen(descriptor, "w") as stream:
        stream.write("# Private local demo configuration; never commit this file.\n")
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    print("Created private .env.docker; use its DEMO_PASSWORD to sign in")


if __name__ == "__main__":
    main()
