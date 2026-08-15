# syntax=docker/dockerfile:1
# ------------------------------------------------------------------------------
# ClipForge frontend — multi-stage build.
# Stage 1: Vite build on node:20-alpine (linux/arm64 + linux/amd64).
# Stage 2: static SPA served by nginx:alpine.
# ------------------------------------------------------------------------------

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
