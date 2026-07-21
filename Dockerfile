# QWED Finance Guard v2.0 Docker Image
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from project metadata (single source of truth)
COPY qwed_finance/ /app/qwed_finance/
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir /app

# Copy action entrypoint
COPY action_entrypoint.py /app/action_entrypoint.py

# Set Python path
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "/app/action_entrypoint.py"]
