# Tally task sandbox: runs one agent task as an unprivileged user under gVisor, with no internet access.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# The embedding model is baked in because the sandbox cannot download anything at run time.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed')" && chmod -R a+rX /opt/fastembed
ENV HF_HUB_OFFLINE=1
RUN useradd --uid 1000 --create-home --home-dir /home/agent agent
COPY --chown=root:root runner.py tally_tools.py /opt/tally/
ENV PYTHONPATH=/opt/tally PYTHONUNBUFFERED=1 HOME=/home/agent \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1
USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["python", "/opt/tally/runner.py"]
