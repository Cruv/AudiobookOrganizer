# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Production
FROM python:3.12-alpine

RUN apk add --no-cache nginx curl shadow

WORKDIR /app

# Install Python dependencies in a separate layer so the heavy
# pip-install step doesn't re-run on every backend code edit. We need
# a stub `app/__init__.py` because pyproject.toml's setuptools
# discovery walks the source tree, and pip otherwise refuses to
# install. Real source is copied in the next layer.
COPY backend/pyproject.toml ./
RUN mkdir -p ./app && touch ./app/__init__.py && \
    pip install --no-cache-dir . && \
    rm -rf ./app

# Now copy the real source. Edits here invalidate this layer only,
# not the (slow) pip-install layer above.
COPY backend/app ./app

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist /app/static

# Copy config files
COPY nginx.conf /etc/nginx/nginx.conf
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data directory
RUN mkdir -p /app/data

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
