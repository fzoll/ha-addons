FROM node:24-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates jq curl python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@11.10.0 --activate

# Claude Code CLI — the provider T3 Code drives for cc_runner sessions.
RUN npm install -g @anthropic-ai/claude-code

# Vite+ CLI, required to build the T3 Code monorepo from source (no published
# Docker image exists for the fzoll/t3code fork).
ENV VP_HOME=/opt/vite-plus
ENV VP_NODE_MANAGER=no
RUN curl -fsSL https://vite.plus | CI=true bash
ENV PATH="${VP_HOME}/bin:${PATH}"

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
