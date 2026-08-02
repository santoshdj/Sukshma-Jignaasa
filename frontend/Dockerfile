# ── Stage 1: build ─────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies (cached layer)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build
COPY . .

# NEXT_PUBLIC_* vars are baked at build time — pass the app name
ARG NEXT_PUBLIC_APP_NAME=Sukshma-Jignaasa
ENV NEXT_PUBLIC_APP_NAME=$NEXT_PUBLIC_APP_NAME

# Clerk public keys (required at build time for client-side code)
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY

ARG NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
ENV NEXT_PUBLIC_CLERK_SIGN_IN_URL=$NEXT_PUBLIC_CLERK_SIGN_IN_URL

ARG NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
ENV NEXT_PUBLIC_CLERK_SIGN_UP_URL=$NEXT_PUBLIC_CLERK_SIGN_UP_URL

ARG NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
ENV NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=$NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL

ARG NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
ENV NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=$NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL

# BACKEND_URL is used in next.config.js rewrites (evaluated at build time)
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL

RUN npm run build

# ── Stage 2: runtime ────────────────────────────────────────────────────────────
# Use Node for next start (next's production server is Node-based)
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Runtime environment variables (injected by Railway at deploy time):
# - CLERK_SECRET_KEY (server-side only, never exposed to client)
# - PORT (Railway-specific, defaults to 3000)

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
