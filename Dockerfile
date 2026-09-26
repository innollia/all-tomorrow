# 04D — All Tomorrow application image.
# Build:  docker build -t all-tomorrow:0.1.0 .
# The digest of the pushed image goes into deploy/docker-compose.yaml (no :latest).
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
RUN pip install .

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Bind to all interfaces INSIDE the container; the host/ALB restricts exposure.
ENV ALL_TOMORROW_HOST=0.0.0.0 \
    ALL_TOMORROW_PORT=8080

EXPOSE 8080

# Container-level healthcheck mirrors the compose probe.
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3).status==200 else 1)"

# Entry point declared in pyproject [project.scripts]: all-tomorrow-api = web:run
CMD ["all-tomorrow-api"]
