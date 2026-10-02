from pathlib import Path
from stat import S_IMODE

from sqlalchemy.engine import make_url

from scripts.init_demo import main


def test_initializer_private_and_preserves_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    main()
    file = Path(".env.docker")
    original = file.read_text()
    values = dict(line.split("=", 1) for line in original.splitlines() if not line.startswith("#"))
    assert S_IMODE(file.stat().st_mode) == 0o600
    assert make_url(values["DATABASE_URL"]).password == values["POSTGRES_PASSWORD"]
    assert make_url(values["DATABASE_URL"]).host == "db"
    main()
    assert file.read_text() == original
    output = capsys.readouterr().out
    assert values["POSTGRES_PASSWORD"] not in output and values["API_AUTH_TOKEN"] not in output
    assert values["DEMO_PASSWORD"] not in output


def test_initializer_adds_missing_runtime_url_without_rotating_password(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    file = Path(".env.docker")
    file.write_text("POSTGRES_PASSWORD=synthetic:password@with/symbols\n")
    main()
    values = dict(line.split("=", 1) for line in file.read_text().splitlines())
    assert make_url(values["DATABASE_URL"]).password == values["POSTGRES_PASSWORD"]
