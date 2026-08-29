# Railway web service keeps the monorepo root as its build context. Keep this
# thin adapter in the root so that the service still builds the web package
# with the same image and SPA fallback as web/Dockerfile.
FROM node:20-alpine AS builder

WORKDIR /app

COPY web/package.json web/package-lock.json* ./
RUN npm install

COPY web/ ./

ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
ARG VITE_BOT_USERNAME
ENV VITE_BOT_USERNAME=$VITE_BOT_USERNAME

RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app
RUN npm install -g serve@latest
COPY --from=builder /app/dist ./dist

EXPOSE 3000
CMD ["sh", "-c", "serve dist -s -l ${PORT:-3000}"]
