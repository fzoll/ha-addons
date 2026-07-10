#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"
ACCESS_TOKEN=$(jq -r '.access_token' "$CONFIG_PATH")
REPOS=$(jq -r '.repos[]' "$CONFIG_PATH")
RUNNER_NAME=$(jq -r '.runner_name' "$CONFIG_PATH")
LABELS=$(jq -r '.labels' "$CONFIG_PATH")

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
  echo "ERROR: access_token not set in add-on config"
  exit 1
fi

RUNNER_DIR="/home/runner"
PIDS=()

# Single runner process handles one repo at a time.
# For multiple repos, we run separate runner processes with separate config dirs.
INDEX=0
for REPO in $REPOS; do
  INDEX=$((INDEX + 1))
  WORK_DIR="/tmp/runner/${REPO##*/}"
  INST_DIR="/data/runner-${INDEX}"

  mkdir -p "$WORK_DIR" "$INST_DIR"

  # Copy full runner if not already there
  if [ ! -f "$INST_DIR/config.sh" ]; then
    echo "Copying runner binaries to instance ${INDEX} ..."
    cp -a "${RUNNER_DIR}/." "$INST_DIR/"
  fi

  echo "Registering runner for ${REPO} ..."

  REG_TOKEN=$(curl -s -X POST \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${REPO}/actions/runners/registration-token" | jq -r .token)

  if [ -z "$REG_TOKEN" ] || [ "$REG_TOKEN" = "null" ]; then
    echo "ERROR: Failed to get registration token for ${REPO}"
    continue
  fi

  INSTANCE_NAME="${RUNNER_NAME}-${REPO##*/}"

  cd "$INST_DIR"
  ./config.sh \
    --url "https://github.com/${REPO}" \
    --token "$REG_TOKEN" \
    --name "$INSTANCE_NAME" \
    --labels "$LABELS" \
    --work "$WORK_DIR" \
    --unattended \
    --replace 2>&1

  echo "Starting runner for ${REPO} as ${INSTANCE_NAME} ..."
  ./run.sh &
  PIDS+=($!)
done

if [ ${#PIDS[@]} -eq 0 ]; then
  echo "ERROR: No runners started"
  exit 1
fi

echo "All runners started (${#PIDS[@]} repos). Waiting..."

cleanup() {
  echo "Shutting down runners..."
  for PID in "${PIDS[@]}"; do
    kill "$PID" 2>/dev/null || true
  done
  echo "Cleanup done"
}

trap cleanup SIGTERM SIGINT

wait
