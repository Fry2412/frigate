FROM python:3.12.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY portal_manager ./portal_manager
RUN pip install --no-cache-dir .
RUN mkdir -p /data && chown 10001:10001 /data
ENV PORTAL_DATA_DIR=/data
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]
CMD ["uvicorn", "portal_manager.server:app", "--host", "0.0.0.0", "--port", "8080"]
