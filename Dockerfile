FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
COPY api ./api
COPY frontend ./frontend
COPY configs ./configs
COPY scripts ./scripts
COPY data/sample ./data/sample
COPY data/annotations ./data/annotations

RUN mkdir -p artifacts data/processed reports

EXPOSE 8000 8501

# The default is the API. docker-compose overrides the frontend command.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
