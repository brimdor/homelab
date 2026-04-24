# Scribe - Runtime container
# The actual Scribe image is built from ~/Documents/Github/scribe and pushed
# to registry.eaglepass.io / 10.0.20.11:32309 during deploy.
# This Dockerfile serves as a local/dev fallback reference only.
FROM node:24-alpine

RUN apk add --no-cache \
    dumb-init \
    ca-certificates \
    curl

WORKDIR /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3100 \
    TZ=America/Chicago

EXPOSE 3100

# The actual deployment uses image: 10.0.20.11:32309/scribe:latest
# which is built and pushed from ~/Documents/Github/scribe using:
#   npm install && npm run build
#   docker build -t registry.eaglepass.io/scribe:latest .
#   docker push registry.eaglepass.io/scribe:latest
#   docker tag registry.eaglepass.io/scribe:latest 10.0.20.11:32309/scribe:latest
#   docker push 10.0.20.11:32309/scribe:latest
#
# This container would need the following copied in to work:
# COPY dist/ dist/
# COPY server/ server/
# COPY node_modules/ node_modules/
# COPY package.json package.json

USER node
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "server/index.js"]
