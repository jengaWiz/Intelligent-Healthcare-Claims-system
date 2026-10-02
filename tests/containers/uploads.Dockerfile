FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.7.17
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY api/ api/
COPY config/ config/
COPY database/ database/
COPY models/ models/
COPY schema/ schema/
COPY services/ services/
COPY scripts/check_upload_restart.py ./smoke.py
CMD ["/app/.venv/bin/python", "/app/smoke.py"]
