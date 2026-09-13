# Multi-stage build for the static-exported Next.js SPA.
#
# Stage 1 builds the SPA (npm ci && npm run build) producing out/.
# Stage 2 serves out/ with a tiny Express static server (server.js). Not nginx.

FROM node:22-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:22-slim AS runtime

ENV NODE_ENV=production \
    PORT=3000

WORKDIR /app

# Only the static export and the server plus its single runtime dependency.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

COPY server.js ./server.js
COPY --from=build /app/out ./out

EXPOSE 3000

CMD ["node", "server.js"]
