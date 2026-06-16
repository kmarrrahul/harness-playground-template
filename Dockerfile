# ─────────────────────────────────────────────────────────────────────────────
# Harness Playground Template
# Copyright (c) 2026. Licensed under the MIT License.
# ─────────────────────────────────────────────────────────────────────────────
# Optimised multi-stage build
#
# Build context: Current directory
# Build command:
#   docker build -t <image> .
#
# Size optimisations:
#   • Stage 1 (copilot-installer): curl, gnupg only here — never in final image
#   --build-arg ENABLE_COPILOT=false      (Saves ~135 MB)
#   --build-arg ENABLE_CLAUDE=false       (Saves ~236 MB)
#   --build-arg ENABLE_CURSOR=false       (Saves ~180 MB)
#   --build-arg ENABLE_ANTIGRAVITY=false  (Saves ~123 MB)
#   --build-arg ENABLE_CODEX=false        (Saves ~150 MB)
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: download the gh CLI ──────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS gh-installer
ARG ENABLE_GH=true

COPY k8s/certs/*.crt /usr/local/share/ca-certificates/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI (gh)
RUN mkdir -p /out/bin \
    && if [ "$ENABLE_GH" = "true" ]; then \
        ARCH=$(dpkg --print-architecture) \
        && mkdir -p /etc/apt/keyrings \
        && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
           | dd of=/etc/apt/keyrings/githubcli-archive-keyring.gpg \
        && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
        && echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
           > /etc/apt/sources.list.d/github-cli.list \
        && apt-get update \
        && apt-get install -y --no-install-recommends gh \
        && cp /usr/bin/gh /out/bin/gh \
        && rm -rf /var/lib/apt/lists/*; \
    fi


# ── Stage 3: Node.js from official image ─────────────────────────────────────
FROM node:20-bookworm-slim AS node-source

# ── Stage 4: runtime image ───────────────────────────────────────────────────
FROM python:3.11-slim-bookworm
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Point Python/OpenSSL at the system CA bundle so enterprise proxies work
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# ── Environment: Copilot CLI defaults ────────────────────────────────────────
ENV COPILOT_MODEL=claude-sonnet-4.6 \
    COPILOT_ALLOW_ALL=true \
    COPILOT_AUTO_UPDATE=false \
    COPILOT_SKILLS_DIRS=/app/app/skills \
    NO_PROXY=github.com,api.github.com,copilot-proxy.githubusercontent.com,*.githubcopilot.com

WORKDIR /app

# ── Step 1: CA certificates + git (git needed for Playground shell ops) ──────
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY k8s/certs/*.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates

# ── Step 2: GitHub CLI (binaries only) ──────────────────────────────────────
COPY --from=gh-installer /out/bin/ /usr/local/bin/

# ── Step 3: Node.js 20 (binary + npm/npx from official image) ───────────────
COPY --from=node-source /usr/local/bin/node /usr/local/bin/node
COPY --from=node-source /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx


# ── Step 5: Python dependencies (includes AWS CLI v1) ───────────────────────
ARG ENABLE_COPILOT=true
ARG ENABLE_CLAUDE=true
ARG ENABLE_CURSOR=true
ARG ENABLE_ANTIGRAVITY=true
ARG ENABLE_CODEX=true

COPY requirements.txt /tmp/requirements.txt

# Conditionally strip out heavy SDKs if the user disabled them via build args
RUN if [ "$ENABLE_COPILOT" = "false" ]; then sed -i '/github-copilot-sdk/d' /tmp/requirements.txt; fi \
    && if [ "$ENABLE_CLAUDE" = "false" ]; then sed -i '/claude-agent-sdk/d' /tmp/requirements.txt; fi \
    && if [ "$ENABLE_CURSOR" = "false" ]; then sed -i '/cursor-sdk/d' /tmp/requirements.txt; fi \
    && if [ "$ENABLE_ANTIGRAVITY" = "false" ]; then \
           sed -i '/google-antigravity/d' /tmp/requirements.txt; \
           sed -i '/google-genai/d' /tmp/requirements.txt; \
       fi \
    && if [ "$ENABLE_CODEX" = "false" ]; then sed -i '/openai-codex/d' /tmp/requirements.txt; fi \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ── Step 6: Application source ──────────────────────────────────────────────
COPY app/ /app/app/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
