# Minimal container for DeepCode web UI using Streamlit
# We use Python slim base image, create non-root user, and install package

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Create a non-root user
RUN useradd -m -u 1000 appuser
WORKDIR /app

# System deps (curl for health/debug), then install deepcode-hku and streamlit
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install the DeepCode package; streamlit is a dependency for the UI path
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir deepcode-hku streamlit

# Copy optional config seeds if provided at build time (safe to miss)
# COPY mcp_agent.config.yaml mcp_agent.secrets.yaml ./

USER 1000:1000
EXPOSE 8501

# Default command launches the web UI
# The upstream docs say `deepcode` starts the UI at :8501
CMD ["deepcode"]
