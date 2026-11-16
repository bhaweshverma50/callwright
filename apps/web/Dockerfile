# Cloud Run image: build the Vite app, then serve dist/ with server.mjs.
# VITE_* values are read at build time from .env.production.local
# (git-ignored, present in the deploy upload).
FROM node:24-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production
COPY server.mjs ./
COPY --from=build /app/dist ./dist
USER node
CMD ["node", "server.mjs"]
