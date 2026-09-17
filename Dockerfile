FROM python:3.12-alpine@sha256:1887c114801a8c82a4ec01daa52cfe7fc3f63573640e2247320289807ac1c3bb

WORKDIR /app
COPY app.py index.html network_collector.py storage_collector.py reliability_collector.py memory_collector.py peer_collector.py ./
COPY static ./static

USER 65532:65532
EXPOSE 8789
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8789/healthz', timeout=2)"]
ENTRYPOINT ["python", "app.py"]
