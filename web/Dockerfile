# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build ----------
FROM node:20-alpine AS builder

WORKDIR /app

# VITE_API_URL must be supplied at build time because Vite bakes it into the
# bundle. In Coolify, set it as a build argument on the web resource.
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

RUN npm run build

# ---------- Stage 2: serve ----------
FROM nginx:alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
