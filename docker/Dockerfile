FROM python:3.12-slim

# The Agent SDK ships its own Claude Code binary; it needs certs and git-free basics only.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 camena

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
# Kokoro voice model (Apache-2.0), fetched at build time and pinned by checksum.
# Its own layer, before the app code, so code changes don't re-download 200 MB.
COPY docker/fetch_kokoro.py /tmp/fetch_kokoro.py
RUN python /tmp/fetch_kokoro.py /opt/kokoro && rm /tmp/fetch_kokoro.py

COPY backend backend
COPY frontend frontend

# HOME lives on the data volume so Claude session transcripts (used to resume
# the conversation) survive container rebuilds.
ENV CAMENA_DATA_DIR=/data \
    CAMENA_TTS_DIR=/opt/kokoro \
    HOME=/data/home \
    PYTHONUNBUFFERED=1
COPY docker/entrypoint.sh /usr/local/bin/camena-entrypoint
RUN mkdir -p /data/home && chown -R camena:camena /data
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health',timeout=4)"
ENTRYPOINT ["tini", "--", "camena-entrypoint"]
