# HeartLib - Music Foundation Model Container
# Multi-stage build for optimized image size

FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3-pip \
    git \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Clone and install heartlib
WORKDIR /build
RUN git clone --depth 1 https://github.com/HeartMuLa/heartlib.git .
RUN pip install --no-cache-dir -e .

# Install Gradio for web interface
RUN pip install --no-cache-dir gradio==4.44.0

# Runtime stage
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy heartlib source
COPY --from=builder /build /app
WORKDIR /app

# Create directories for models and outputs
RUN mkdir -p /models /output

# Copy the Gradio app and entrypoint
COPY app.py /app/app.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose Gradio port
EXPOSE 7860

# Health check - increased start period for model download
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=3 \
    CMD python3.10 -c "import requests; requests.get('http://localhost:7860')" || exit 1

# Use entrypoint for model download and app startup
ENTRYPOINT ["/app/entrypoint.sh"]
