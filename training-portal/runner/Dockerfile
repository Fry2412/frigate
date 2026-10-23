# Official PyTorch image pins the framework and CUDA/cuDNN runtime together.
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385

ARG YOLOV9_COMMIT=5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff
ENV PYTHONUNBUFFERED=1 \
    YOLO_SOURCE_DIR=/opt/yolov9 \
    YOLO_WEIGHTS=/weights/yolov9-s.pt

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/portal-runner
RUN git init /opt/yolov9 \
    && git -C /opt/yolov9 remote add origin https://github.com/WongKinYiu/yolov9.git \
    && git -C /opt/yolov9 fetch --depth 1 origin "${YOLOV9_COMMIT}" \
    && git -C /opt/yolov9 checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/yolov9 rev-parse HEAD)" = "${YOLOV9_COMMIT}"

COPY requirements-gpu.txt ./requirements-gpu.txt
RUN python -m pip install --no-cache-dir -r requirements-gpu.txt

COPY pyproject.toml ./pyproject.toml
COPY src ./src
# Reinstall after copying package metadata/source. The build deliberately does
# not fetch weights; mount a trusted local checkpoint or set YOLO_WEIGHTS="".
RUN python -m pip install --no-cache-dir --no-build-isolation --no-deps . \
    && mkdir -p /var/lib/portal-runner /weights

VOLUME ["/var/lib/portal-runner", "/weights"]
ENTRYPOINT ["portal-runner"]
