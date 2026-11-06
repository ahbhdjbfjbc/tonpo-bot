# Canonical runtime: Python 3.12 (matches README, pyproject.toml and .python-version)
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories and run as an unprivileged user
RUN groupadd --system --gid 10001 tonpo \
    && useradd --system --uid 10001 --gid tonpo --home-dir /app --shell /usr/sbin/nologin tonpo \
    && mkdir -p logs data \
    && chown -R tonpo:tonpo logs data
USER tonpo

# Run the application
CMD ["python", "main.py"]
