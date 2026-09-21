FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN pip install --no-cache-dir pytest==8.4.2 ruff==0.12.12 mypy==1.17.1 packaging==25.0
RUN mkdir -p /input /workspace /deps /wheels && chmod 1777 /workspace /deps /wheels
COPY sandbox_worker.py /opt/patchwatch/worker.py
USER 65534:65534
WORKDIR /workspace
ENTRYPOINT ["python", "-I", "/opt/patchwatch/worker.py"]
