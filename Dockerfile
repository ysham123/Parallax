FROM node:22.20.0-bookworm-slim AS node
FROM python:3.13.7-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update && apt-get install -y --no-install-recommends git bubblewrap socat ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock
COPY src ./src
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PARALLAX_HOME=/data/parallax PARALLAX_PROJECTS_ROOT=/data/projects
# Provider CLIs are optional and must be installed/authenticated in a custom image.
CMD ["python", "-m", "parallax.cloud"]
