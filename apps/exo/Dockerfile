# Exo Dockerfile - Run your own AI cluster
# Build from exo source directory:
#   docker build -t docker.io/brimdor/exo:latest \
#     -f /path/to/homelab/apps/exo/Dockerfile \
#     /path/to/exo
#
# Based on exo-explore/exo installation instructions

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install uv (Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Rust (required for some dependencies)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"
RUN rustup toolchain install nightly

WORKDIR /app

# Copy local exo source (build context should be exo source directory)
COPY . .

# Build dashboard
WORKDIR /app/dashboard
RUN npm install && npm run build

WORKDIR /app

# Create data directory for models
RUN mkdir -p /data/models

# Expose API/Dashboard port
EXPOSE 52415

# Environment variables for Kubernetes discovery
ENV EXO_LISTEN_PORT=52415
ENV EXO_DATA_DIR=/data/models

# Default command - can be overridden with discovery args
ENTRYPOINT ["uv", "run", "exo"]
CMD ["--api-port", "52415"]
