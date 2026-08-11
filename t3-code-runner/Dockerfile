FROM node:24-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates jq curl python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@11.10.0 --activate

# Claude Code CLI — the provider T3 Code drives for cc_runner sessions.
RUN npm install -g @anthropic-ai/claude-code

# GitHub CLI — T3 Code shells out to `gh` for pull-request lookups and the
# commit/push/PR flow. Without it every PR status probe fails.
ARG GH_VERSION=2.63.2
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      arm64) GH_ARCH=arm64 ;; \
      amd64) GH_ARCH=amd64 ;; \
      *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${GH_ARCH}.tar.gz" -o /tmp/gh.tar.gz; \
    tar -xzf /tmp/gh.tar.gz -C /tmp; \
    mv "/tmp/gh_${GH_VERSION}_linux_${GH_ARCH}/bin/gh" /usr/local/bin/gh; \
    chmod +x /usr/local/bin/gh; \
    rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${GH_ARCH}"; \
    gh --version

# Vite+ CLI, required to build the T3 Code monorepo from source (no published
# Docker image exists for the fzoll/t3code fork).
ENV VP_HOME=/opt/vite-plus
ENV VP_NODE_MANAGER=no
RUN curl -fsSL https://vite.plus | CI=true bash
ENV PATH="${VP_HOME}/bin:${PATH}"

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
