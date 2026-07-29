# ============================================================
# Dockerfile — AstraQuote Lead Engine (Production VPS)
# Oracle Cloud ARM Ubuntu / Any Docker host
# ============================================================

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8800

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libglib2.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libssl-dev \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (skip crawl4ai on VPS — uses httpx fallback)
COPY requirements.txt .
RUN grep -v "crawl4ai" requirements.txt > requirements_vps.txt && \
    pip install --no-cache-dir -r requirements_vps.txt

# Copy application code
COPY . .

# Create persistent dirs
RUN mkdir -p data exports logs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8800/ || exit 1

EXPOSE 8800

CMD ["python", "vps_start.py"]
