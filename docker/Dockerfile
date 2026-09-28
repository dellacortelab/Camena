FROM python:3.12-slim

# The Agent SDK ships its own Claude Code binary; it needs certs and git-free basics only.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 camena

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend

# HOME lives on the data volume so Claude session transcripts (used to resume
# the conversation) survive container rebuilds.
ENV CAMENA_DATA_DIR=/data \
    HOME=/data/home \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data/home && chown -R camena:camena /data
USER camena
WORKDIR /app/backend
EXPOSE 8000
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
