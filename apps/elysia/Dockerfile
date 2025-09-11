# Dockerfile for Elysia (installed via pip from GitHub)
# Based on instructions in https://github.com/weaviate/elysia

FROM python:3.12-slim

# Metadata
LABEL org.opencontainers.image.title="elysia"
LABEL org.opencontainers.image.source="https://github.com/weaviate/elysia"

# Install system dependencies needed for building/installing and runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       git \
       curl \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
ARG USER=elysia
ARG UID=1000
RUN useradd --system --create-home --uid ${UID} ${USER}
WORKDIR /home/${USER}

# Install the package from GitHub (pip will resolve dependencies)
# Pinning to 'main' by default; you can change to a tag by building with --build-arg ELYSIA_REF=vX.Y.Z
ARG ELYSIA_REF=main
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install elysia-ai \
    && python -m pip cache purge || true

# Expose default port (chart uses 8080 by default)
EXPOSE 8080

# Switch to non-root user
USER ${USER}

# Assumption: elysia provides a CLI entrypoint `elysia` or an ASGI app callable. Use `elysia` CLI if present.
# Default command tries `elysia` executable. If that's different, override CMD when running or edit accordingly.
CMD ["elysia start"]
