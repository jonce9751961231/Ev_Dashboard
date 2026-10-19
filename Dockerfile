# ==============================================================================
# ThermaPulse EV Cockpit - Container Dockerfile
# Multi-Model Predictive Thermal Management & Telemetry Simulator Host
# ==============================================================================
FROM python:3.11-slim

WORKDIR /app

# Set container environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEMO_MODE=0 \
    PORT=8000

# Install minimal OS build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code, datasets, and web dashboard
COPY core_server/ core_server/
COPY dashboard_ui/ dashboard_ui/
COPY datasets/ datasets/

# Non-root user for security best practices
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + str(__import__('os').getenv('PORT', 8000)) + '/api/health')" || exit 1

# Launch host app using Uvicorn on dynamic $PORT
CMD ["sh", "-c", "uvicorn core_server.host_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
