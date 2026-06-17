FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

RUN useradd -m -u 1000 sandbox && \
    mkdir -p /artifacts && \
    chown -R sandbox:sandbox /app /artifacts

USER sandbox

ENV ARTIFACTS_DIR=/artifacts
ENV MAX_EXECUTION_SECONDS=30
ENV MAX_MEMORY_MB=256
ENV PORT=9002

EXPOSE 9002

CMD ["python", "-u", "server.py"]
