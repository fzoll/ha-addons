FROM debian:bookworm-slim

ARG RUNNER_VERSION=2.325.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl jq git ca-certificates \
    libicu72 libssl3 libkrb5-3 zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home/runner

RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64) RUNNER_ARCH=x64 ;; \
      aarch64) RUNNER_ARCH=arm64 ;; \
    esac && \
    curl -sL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" | tar xz

COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
