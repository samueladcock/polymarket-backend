# Python base
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable buffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy source
COPY . /app

# Default command runs the one-off script; override to run the API service
# Example to run API: docker run -e PORT=8080 -p 8080:8080 IMAGE \
#        sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"
CMD ["python", "fetch_order.py"]
