FROM node:lts-trixie-slim AS base
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gh git mariadb-client postgresql-client procps \
  && rm -rf /var/lib/apt/lists/*
RUN corepack enable

ARG OPENCODE_VERSION=1.3.0

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
RUN npm install --global --omit=dev @anthropic-ai/claude-code@latest @openai/codex@latest \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) target="linux-x64" ;; \
    arm64) target="linux-arm64" ;; \
    *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
  esac \
  && tmpdir="$(mktemp -d)" \
  && curl -fsSL -o "$tmpdir/opencode.tar.gz" "https://github.com/anomalyco/opencode/releases/download/${OPENCODE_VERSION}/opencode-${target}.tar.gz" \
  && tar -xzf "$tmpdir/opencode.tar.gz" -C "$tmpdir" \
  && install -m 0755 "$tmpdir/opencode" /usr/local/bin/opencode \
  && rm -rf "$tmpdir"

ENV NODE_ENV=production \
  HOME=/home/node \
  HOST=0.0.0.0 \
  PORT=3100 \
  SERVE_UI=true \
  PAPERCLIP_OPENCODE_COMMAND=/usr/local/bin/opencode \
  PAPERCLIP_HOME=/paperclip \
  PAPERCLIP_INSTANCE_ID=default \
  PAPERCLIP_CONFIG=/paperclip/instances/default/config.json \
  PAPERCLIP_DEPLOYMENT_MODE=authenticated \
  PAPERCLIP_DEPLOYMENT_EXPOSURE=private

VOLUME ["/paperclip"]
EXPOSE 3100

USER node
CMD ["node", "--import", "./server/node_modules/tsx/dist/loader.mjs", "server/dist/index.js"]
