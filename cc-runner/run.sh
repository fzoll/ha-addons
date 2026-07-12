#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"
SERVER_URL=$(jq -r '.server_url' "$CONFIG_PATH")
RUNNER_TOKEN=$(jq -r '.runner_token' "$CONFIG_PATH")
RUNNER_NAME=$(jq -r '.runner_name' "$CONFIG_PATH")
MAX_SLOTS=$(jq -r '.max_slots' "$CONFIG_PATH")
EXECUTOR_IMAGE=$(jq -r '.executor_image' "$CONFIG_PATH")
GH_TOKEN=$(jq -r '.gh_token' "$CONFIG_PATH")

if [ -z "$SERVER_URL" ] || [ "$SERVER_URL" = "null" ]; then
  echo "ERROR: server_url not set in add-on config"
  exit 1
fi
if [ -z "$RUNNER_TOKEN" ] || [ "$RUNNER_TOKEN" = "null" ]; then
  echo "ERROR: runner_token not set in add-on config"
  exit 1
fi

# cc_runner is a private repo, so a GH token is needed to clone it. Prefer the
# addon config value; fall back to the CC Runner server's secret vault.
if [ -z "$GH_TOKEN" ] || [ "$GH_TOKEN" = "null" ]; then
  echo "No gh_token in add-on config, fetching from CC Runner server vault..."
  GH_TOKEN=$(curl -sf -H "Authorization: Bearer ${RUNNER_TOKEN}" \
    "${SERVER_URL%/}/api/runner/secrets/gh_token:fzoll" | jq -r '.value')
fi
if [ -z "$GH_TOKEN" ] || [ "$GH_TOKEN" = "null" ]; then
  echo "ERROR: could not obtain gh_token (set it in add-on config or the CC Runner server vault)"
  exit 1
fi

CC_RUNNER_DIR="/data/cc_runner"
REPO_URL="https://github.com/fzoll/cc_runner.git"
AUTH="Authorization: Basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)"

git_auth() {
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=http.extraheader \
  GIT_CONFIG_VALUE_0="$AUTH" \
    git "$@"
}

if [ ! -d "$CC_RUNNER_DIR/.git" ]; then
  echo "Cloning cc_runner (first run)..."
  git_auth clone --depth=1 "$REPO_URL" "$CC_RUNNER_DIR"
else
  echo "Updating cc_runner..."
  # Heals installs that already have a tokenized URL persisted
  git -C "$CC_RUNNER_DIR" remote set-url origin "$REPO_URL"
  git_auth -C "$CC_RUNNER_DIR" fetch --depth=1 origin
  git -C "$CC_RUNNER_DIR" reset --hard origin/HEAD
fi

echo "Building runner..."
cd "$CC_RUNNER_DIR"
pnpm install --frozen-lockfile
pnpm --filter @cc-runner/shared build
pnpm --filter @cc-runner/runner build

export SERVER_URL
export RUNNER_TOKEN
export RUNNER_NAME="${RUNNER_NAME:-ha-runner}"
export RUNNER_MAX_SLOTS="${MAX_SLOTS:-1}"
export EXECUTOR_IMAGE

# Persistent across addon restarts
export PENDING_DIR="/data/pending"
mkdir -p "$PENDING_DIR"

exec node apps/runner/dist/index.js
