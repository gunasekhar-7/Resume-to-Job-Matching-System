FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

COPY requirements.txt requirements.lock ./
# Install the CPU wheel first: the default PyPI Linux torch wheel pulls several GB of
# CUDA/NVIDIA libraries that this CPU-only service never uses.
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple torch
RUN pip install -r requirements.lock

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY api ./api
COPY frontend ./frontend
COPY configs ./configs
COPY scripts ./scripts
COPY data/sample ./data/sample
COPY data/annotations ./data/annotations

RUN mkdir -p artifacts data/processed data/raw data/interim reports \
    && chown -R app:app /app/artifacts /app/data /app/reports

USER app

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -fsS http://localhost:8000/ready || exit 1

# The default is the API. docker-compose overrides the frontend command.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
