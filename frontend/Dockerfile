# ── Stage 1: build ─────────────────────────────────────────────────────────────
FROM oven/bun:1-alpine AS builder

WORKDIR /app

# Install dependencies (cached layer)
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Copy source and build
COPY . .

# NEXT_PUBLIC_* vars are baked at build time — pass the app name
ARG NEXT_PUBLIC_APP_NAME=Sukshma-Jignaasa
ENV NEXT_PUBLIC_APP_NAME=$NEXT_PUBLIC_APP_NAME

# BACKEND_URL is used in next.config.js rewrites (evaluated at build time)
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL

RUN bun run build

# ── Stage 2: runtime ────────────────────────────────────────────────────────────
# Use Node for next start (next's production server is Node-based)
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Copy built output and runtime dependencies
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.js ./next.config.js

# public/ folder (static assets) — copy only if it exists
COPY --from=builder /app/public* ./public/

EXPOSE 3000

# Railway injects $PORT; Next.js 14 honours the PORT env var natively
CMD ["sh", "-c", "node_modules/.bin/next start -p ${PORT:-3000}"]
