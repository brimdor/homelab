# Postgres with pgvector extension for n8n
FROM postgres:18.1-bookworm

# Install pgvector (extension name: "vector")
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-17-pgvector; \
    rm -rf /var/lib/apt/lists/*
