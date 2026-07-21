# QWED Finance Guard v2.0 Docker Image
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install third-party dependencies first (cached unless pyproject.toml changes)
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir sympy>=1.12 mpmath>=1.3.0 sqlglot>=20.0.0 z3-solver>=4.12.0 jsonschema>=4.0.0 pandas>=2.0

# Then copy source and install the package itself
COPY qwed_finance/ /app/qwed_finance/
RUN pip install --no-cache-dir --no-deps /app

# Copy action entrypoint
COPY action_entrypoint.py /app/action_entrypoint.py

# Set Python path
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "/app/action_entrypoint.py"]
