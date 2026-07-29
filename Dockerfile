# Use lightweight official Python image
FROM python:3.11-slim

# Prevent Python from writing pyc files and buffer output
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt-get/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite persistence
RUN mkdir -p data exports

# Expose Dashboard Port
EXPOSE 8800

# Default command launches pipeline and serves Dashboard
CMD ["python", "main.py"]
