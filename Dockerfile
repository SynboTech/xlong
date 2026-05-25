FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts
COPY docs ./docs

ENV PYTHONPATH=/app/src
RUN chmod +x scripts/*.sh scripts/*.py

CMD ["python", "-m", "mm.main", "--config", "config/paper.json"]
