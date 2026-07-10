ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:3.21
FROM ${BUILD_FROM}

ARG RUNNER_VERSION=2.325.0

RUN apk add --no-cache \
    bash curl jq git docker-cli nodejs npm \
    icu-libs lttng-ust krb5-libs zlib libssl3

WORKDIR /home/runner

RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64) RUNNER_ARCH=x64 ;; \
      aarch64) RUNNER_ARCH=arm64 ;; \
      *) echo "Unsupported: $ARCH" && exit 1 ;; \
    esac && \
    curl -sL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" | tar xz

COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
