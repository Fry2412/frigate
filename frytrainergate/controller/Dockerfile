# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY frytrainergate/controller/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY frytrainergate /app/frytrainergate

RUN useradd --create-home --uid 10001 frytrainergate \
    && mkdir -p /data \
    && chown -R frytrainergate:frytrainergate /app /data
USER frytrainergate

EXPOSE 8972 8974
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "frytrainergate.controller"]

