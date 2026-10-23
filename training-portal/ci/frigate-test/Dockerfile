FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Frigate normally generates this during its image build. Provide the same module in the test image.
RUN mkdir -p /tmp/frigate-test-init && printf '%s\n' \
    'import sys, types' \
    'version = types.ModuleType("frigate.version")' \
    'version.VERSION = "test"' \
    'sys.modules["frigate.version"] = version' \
    > /tmp/frigate-test-init/sitecustomize.py

ENV PYTHONPATH=/workspace:/tmp/frigate-test-init

CMD ["python", "-m", "pytest", "-q"]
