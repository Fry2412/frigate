# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

WORKDIR /app
COPY frytrainergate/runner/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY frytrainergate /app/frytrainergate

RUN useradd --create-home --uid 10001 frytrainergate \
    && mkdir -p /data \
    && chown -R frytrainergate:frytrainergate /app /data
USER frytrainergate

VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "frytrainergate.runner"]

