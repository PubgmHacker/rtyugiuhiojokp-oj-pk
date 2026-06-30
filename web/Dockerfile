# ── Build stage ─────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Build-time env — VITE_API_URL должен быть публичным
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
ARG VITE_BOT_USERNAME
ENV VITE_BOT_USERNAME=$VITE_BOT_USERNAME

RUN npm run build

# ── Serve stage ─────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

RUN npm install -g serve@latest

COPY --from=builder /app/dist ./dist

EXPOSE 3000

# SPA fallback (-s) чтобы react-router работал
CMD ["sh", "-c", "serve dist -s -l ${PORT:-3000}"]
