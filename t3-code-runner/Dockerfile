FROM node:24-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates jq curl openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — a provider T3 Code drives.
#
# npm 11 blocks package install scripts by default, and recent claude-code
# releases ship the real CLI as a platform-native optional dependency that a
# postinstall step unpacks. Without --allow-scripts the install "succeeds" but
# leaves only a stub that exits with "claude native binary not installed",
# which surfaces much later as a PlatformError on every session start.
RUN npm install -g --allow-scripts=@anthropic-ai/claude-code @anthropic-ai/claude-code \
    && claude --version

# Codex CLI — the OpenAI provider T3 Code drives.
#
# Pinned like T3 itself so every node runs the same build. To upgrade, change
# CODEX_VERSION and bump the add-on version in config.yaml. The binary ships as
# a platform-native optional dependency, so the --version check also proves the
# right one was installed.
ARG CODEX_VERSION=0.167.2
RUN npm install -g "@openai/codex@${CODEX_VERSION}" \
    && codex --version

# GitHub CLI — T3 Code and its agents use `gh` for pull requests, and git uses
# it as the credential helper.
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

# Official T3 Code release (https://github.com/pingdotgg/t3code), unmodified.
#
# The version is pinned so every node in the fleet runs the same build: T3
# clients and servers must speak the same protocol version. To upgrade, change
# T3_VERSION and both checksums (from the release's SHA256SUMS file) together,
# and bump the add-on version in config.yaml.
ARG T3_VERSION=0.1.9
ARG T3_SHA256_ARM64=52023bc5728a4dee4de361ad6fef7c236f1efb2742ff25e29d5c55e2fb662eea
ARG T3_SHA256_X64=0141025335da334759cecd8db3483e09772f3600ca03674698524e7d94291362
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      arm64) T3_ARCH=arm64; T3_SHA256="${T3_SHA256_ARM64}" ;; \
      amd64) T3_ARCH=x64; T3_SHA256="${T3_SHA256_X64}" ;; \
      *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/pingdotgg/t3code/releases/download/v${T3_VERSION}/t3-${T3_VERSION}-linux-${T3_ARCH}.tar.gz" -o /tmp/t3.tar.gz; \
    echo "${T3_SHA256}  /tmp/t3.tar.gz" | sha256sum -c -; \
    mkdir -p /opt/t3; \
    tar -xzf /tmp/t3.tar.gz -C /opt/t3 --strip-components=1; \
    rm -f /tmp/t3.tar.gz; \
    ln -s /opt/t3/t3 /usr/local/bin/t3; \
    t3 --version

# cloudflared — the relay client T3 Connect uses for its managed tunnel.
#
# T3 Code offers to download it, but only through an interactive y/N prompt,
# which an add-on has no terminal to answer. Ship the exact version this T3
# release expects (`t3 connect status --json` reports it as relayClient.version)
# so T3 finds it on PATH. Bump it together with T3_VERSION when that changes.
ARG CLOUDFLARED_VERSION=2026.10.4
ARG CLOUDFLARED_SHA256_ARM64=2b7203b4fb0ba28a0c1e12f8855ce2c25f76d266a8d5edafac5540b6812acff6
ARG CLOUDFLARED_SHA256_AMD64=ae5e8add7884b0531d66bbca4570d1de491ff6da51e4ebe7eb160cdf241d9e42
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      arm64) CF_ARCH=arm64; CF_SHA256="${CLOUDFLARED_SHA256_ARM64}" ;; \
      amd64) CF_ARCH=amd64; CF_SHA256="${CLOUDFLARED_SHA256_AMD64}" ;; \
      *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${CF_ARCH}" -o /usr/local/bin/cloudflared; \
    echo "${CF_SHA256}  /usr/local/bin/cloudflared" | sha256sum -c -; \
    chmod +x /usr/local/bin/cloudflared; \
    cloudflared --version

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
