# syntax=docker/dockerfile:1

# --- Builder: install the package + dependencies into an isolated venv -----
FROM python:3.12-slim AS builder

WORKDIR /app

# build-essential is needed to build any C-extension dependencies from
# source if a matching prebuilt wheel isn't available for the target
# platform; it never ships in the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# --- Runtime: copy only the venv + application code ------------------------
FROM python:3.12-slim AS runtime

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin craftcord

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --chown=craftcord:craftcord alembic.ini ./
COPY --chown=craftcord:craftcord alembic/ alembic/
COPY --chown=craftcord:craftcord src/ src/
COPY --chown=craftcord:craftcord scripts/entrypoint.sh scripts/entrypoint.sh
RUN chmod +x scripts/entrypoint.sh

USER craftcord

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["python", "-m", "craftcord"]
