FROM node:lts-trixie-slim AS base
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    composer \
    curl \
    default-jdk-headless \
    dnsutils \
    fd-find \
    gh \
    git \
    golang-go \
    jq \
    less \
    libffi-dev \
    libsqlite3-dev \
    libssl-dev \
    make \
    mariadb-client \
    nano \
    netcat-openbsd \
    openssh-client \
    pkg-config \
    php-cli \
    php-curl \
    php-mbstring \
    php-sqlite3 \
    php-xml \
    php-zip \
    postgresql-client \
    procps \
    python-is-python3 \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    python3-full \
    pipx \
    ripgrep \
    ruby-full \
    rustc \
    rsync \
    sqlite3 \
    unzip \
    xz-utils \
    zip \
    cargo \
    maven \
  && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
  && gem install --no-document bundler \
  && rm -rf /var/lib/apt/lists/*
RUN corepack enable

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY cli/package.json cli/
COPY server/package.json server/
COPY ui/package.json ui/
COPY packages/shared/package.json packages/shared/
COPY packages/db/package.json packages/db/
COPY packages/adapter-utils/package.json packages/adapter-utils/
COPY packages/adapters/claude-local/package.json packages/adapters/claude-local/
COPY packages/adapters/codex-local/package.json packages/adapters/codex-local/
COPY packages/adapters/cursor-local/package.json packages/adapters/cursor-local/
COPY packages/adapters/gemini-local/package.json packages/adapters/gemini-local/
COPY packages/adapters/openclaw-gateway/package.json packages/adapters/openclaw-gateway/
COPY packages/adapters/opencode-local/package.json packages/adapters/opencode-local/
COPY packages/adapters/pi-local/package.json packages/adapters/pi-local/
COPY packages/plugins/sdk/package.json packages/plugins/sdk/

RUN pnpm install --frozen-lockfile

FROM base AS build
WORKDIR /app
COPY --from=deps /app /app
COPY . .
RUN pnpm --filter @paperclipai/ui build
RUN pnpm --filter @paperclipai/plugin-sdk build
RUN pnpm --filter @paperclipai/server build
RUN test -f server/dist/index.js || (echo "ERROR: server build output missing" && exit 1)

FROM base AS production
WORKDIR /app
RUN usermod -o -u 0 node \
  && usermod -g 0 node \
  && node -e "const fs=require('fs'); const p='/etc/passwd'; const text=fs.readFileSync(p,'utf8').replace(/^root:([^:]*:[0-9]+:[0-9]+:[^:]*:)\/root:/m, 'root:$1/home/node:'); fs.writeFileSync(p, text);" \
  && mkdir -p /home/node /paperclip \
  && chown -R 0:0 /home/node /paperclip
COPY --chown=0:0 --from=build /app /app

ENV NODE_ENV=production \
  HOME=/home/node \
  HOST=0.0.0.0 \
  PORT=3100 \
  SERVE_UI=true \
  PAPERCLIP_OPENCODE_COMMAND=/home/node/.opencode/bin/opencode \
  PAPERCLIP_HOME=/paperclip \
  PAPERCLIP_INSTANCE_ID=default \
  PAPERCLIP_CONFIG=/paperclip/instances/default/config.json \
  PAPERCLIP_DEPLOYMENT_MODE=authenticated \
  PAPERCLIP_DEPLOYMENT_EXPOSURE=private

VOLUME ["/paperclip"]
EXPOSE 3100

USER node
CMD ["node", "--import", "./server/node_modules/tsx/dist/loader.mjs", "server/dist/index.js"]
