FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

ARG PUID=1000
ARG PGID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${PGID}" mediafinder \
    && useradd --uid "${PUID}" --gid "${PGID}" --home-dir /app --shell /usr/sbin/nologin mediafinder \
    && mkdir -p /config \
    && chown -R mediafinder:mediafinder /app /config

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=mediafinder:mediafinder . .
RUN chmod +x /app/scripts/entrypoint.sh

ENV PUID=1000 \
    PGID=1000

EXPOSE 8091

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('APP_PORT', '8091'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3)"

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
