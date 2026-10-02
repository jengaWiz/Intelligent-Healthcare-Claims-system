FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH
WORKDIR /app
RUN pip install --no-cache-dir uv==0.7.17
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY api/ api/
COPY agents/ agents/
COPY config/ config/
COPY database/ database/
COPY extractors/ extractors/
COPY models/ models/
COPY schema/ schema/
COPY services/ services/
COPY worker/ worker/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY web/ web/
COPY samples/ samples/
COPY alembic.ini ./
RUN groupadd --gid 10001 claims && useradd --uid 10001 --gid claims --no-create-home claims && mkdir -p /data/uploads && chown -R claims:claims /data
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "api"]
