FROM python:3.12-slim

# Build deps for packages with C extensions (numpy, Pillow, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc git \
    && rm -rf /var/lib/apt/lists/*

# MAST_common is injected at runtime via docker-compose volumes:
#   ../MAST/MAST_common  →  /mast_deps/common        (for internal 'from common.xxx')
#   ../MAST/MAST_common  →  /mast_deps/MAST_common   (for 'from MAST_common.xxx')
# Adding /mast_deps to PYTHONPATH makes both import paths resolve.
ENV PYTHONPATH=/mast_deps:/app/src

# Use an isolated venv so volume mounts to /app don't shadow installed packages
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

RUN pip install --upgrade pip uv

WORKDIR /app

# Install MAST_scheduler and all dependencies (includes MAST_common's transitive deps)
COPY pyproject.toml .
RUN uv pip install --python /opt/venv -e ".[dev]"

# Source is mounted at runtime for live reload; this copy is for image-only runs
COPY src/ src/
COPY tests/ tests/

EXPOSE 8000
