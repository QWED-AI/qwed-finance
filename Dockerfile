# QWED Finance Guard v2.0 Docker Image
FROM python:3.14.4-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from project metadata (single source of truth)
COPY pyproject.toml /app/pyproject.toml
COPY qwed_finance/ /app/qwed_finance/
RUN pip install --no-cache-dir /app pandas

# Copy action entrypoint
COPY action_entrypoint.py /app/action_entrypoint.py

# Set Python path
ENV PYTHONPATH=/app

# Make entrypoint executable
RUN chmod +x /app/action_entrypoint.py

ENTRYPOINT ["python", "/app/action_entrypoint.py"]
