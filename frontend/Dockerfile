FROM node:24-alpine AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM caddy:2.8-alpine AS runner

COPY --from=builder /app/dist /srv/www
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443
