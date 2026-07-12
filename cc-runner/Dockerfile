FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates jq curl \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
