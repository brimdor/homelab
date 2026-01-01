# Exo Dockerfile - Run your own AI cluster
# Build from exo source directory:
#   docker build -t docker.io/brimdor/exo:latest \
#     -f /path/to/homelab/apps/exo/Dockerfile \
#     /path/to/exo
#
# Based on exo-explore/exo installation instructions

FROM python:3.14-slim

# Install system dependencies (GCC 12 required for MLX CPU JIT compatibility)
# GCC 14 causes: "redeclaration of C++ built-in type '_Float128'" errors
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    g++-12 \
    gcc-12 \
    make \
    libc6-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-12 100 \
    && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 100 \
    && update-alternatives --install /usr/bin/cc cc /usr/bin/gcc-12 100

# Install uv (Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Rust (required for exo_pyo3_bindings)
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

# Install Python dependencies AND build the project at build time
# This prevents slow startup from downloading/building on every pod start
# --frozen ensures we use the lockfile exactly as-is
RUN uv sync --frozen

# Pre-build the project to avoid runtime building
# This runs the project in dev mode once to trigger editable install build
RUN uv run python -c "import exo; print('Exo pre-built successfully')"

# Create data directory for models
RUN mkdir -p /data/models

# Expose API/Dashboard port
EXPOSE 52415

# Environment variables for Kubernetes discovery
ENV EXO_LISTEN_PORT=52415
ENV EXO_DATA_DIR=/data/models

# Use the venv directly to skip uv run overhead
# The exo script was installed by uv sync
ENTRYPOINT ["/app/.venv/bin/python", "-m", "exo.main"]
CMD ["--api-port", "52415"]
