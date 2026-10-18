# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    INFINITY_MODE=beta INFINITY_DATA_DIR=/data \
    XDG_CACHE_HOME=/tmp/infinity-cache XDG_DATA_HOME=/data \
    INFINITY_ENFORCE_PUBLIC_PREFLIGHT=1
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.lock
RUN useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
COPY --chown=app:app . .
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
CMD ["python", "service.py"]
