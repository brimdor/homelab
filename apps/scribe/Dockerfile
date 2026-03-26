FROM node:20-alpine AS base
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY server/package.json server/
RUN npm install --global pnpm@9 \
  && pnpm install --frozen-lockfile

FROM base AS build
WORKDIR /app
COPY --from=deps /app/node_modules /app/node_modules
COPY . .
RUN pnpm build

FROM base AS production
RUN apk add --no-cache \
  dumb-init \
  ca-certificates \
  curl

COPY --from=build /app/dist /app/dist
COPY --from=build /app/server /app/server
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/package.json /app/package.json

ENV NODE_ENV=production \
  HOST=0.0.0.0 \
  PORT=3100 \
  TZ=America/Chicago

EXPOSE 3100

USER node
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "server/index.js"]
