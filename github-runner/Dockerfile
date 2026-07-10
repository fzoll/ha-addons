FROM debian:bookworm-slim

ARG RUNNER_VERSION=2.325.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl jq git ca-certificates \
    libicu72 libssl3 libkrb5-3 zlib1g \
    docker.io nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# s6-overlay for HA add-on compatibility
ARG S6_OVERLAY_VERSION=3.2.0.2
RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64) S6_ARCH=x86_64 ;; \
      aarch64) S6_ARCH=aarch64 ;; \
    esac && \
    curl -sL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" | tar Jxpf - -C / && \
    curl -sL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" | tar Jxpf - -C /

WORKDIR /home/runner

RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64) RUNNER_ARCH=x64 ;; \
      aarch64) RUNNER_ARCH=arm64 ;; \
    esac && \
    curl -sL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" | tar xz

COPY run.sh /
RUN chmod a+x /run.sh

ENTRYPOINT ["/init"]
CMD []

COPY rootfs /
