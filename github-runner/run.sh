#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"
ACCESS_TOKEN=$(jq -r '.access_token' "$CONFIG_PATH")
REPOS=$(jq -r '.repos[]' "$CONFIG_PATH")
RUNNER_NAME=$(jq -r '.runner_name' "$CONFIG_PATH")
LABELS=$(jq -r '.labels // ""' "$CONFIG_PATH")

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
  echo "ERROR: access_token not set in add-on config"
  exit 1
fi

if [ -z "$LABELS" ] || [ "$LABELS" = "null" ]; then
  echo "WARNING: labels is empty. The runner will only get the automatic self-hosted/linux/arch labels;" \
       "any workflow whose runs-on names a custom label will never match this runner."
fi

RUNNER_DIR="/home/runner"
export RUNNER_ALLOW_RUNASROOT=1
PIDS=()

for REPO in $REPOS; do
  SAFE_NAME="${REPO//\//-}"
  INST_DIR="/data/runner-${SAFE_NAME}"
  WORK_DIR="/tmp/runner/${SAFE_NAME}"
  INSTANCE_NAME="${RUNNER_NAME}-${SAFE_NAME}"

  mkdir -p "$WORK_DIR"

  if [ ! -x "${INST_DIR}/run.sh" ]; then
    echo "Copying runner binaries for ${REPO} ..."
    rm -rf "$INST_DIR"
    cp -a "${RUNNER_DIR}/." "$INST_DIR/"
  fi

  cd "$INST_DIR"

  # Registration credentials persist in $INST_DIR, so restarts normally reuse
  # them and keep working even if the PAT expired. But re-register whenever
  # runner_name/labels changed since the last registration, so config edits
  # actually take effect (--replace below swaps the old entry cleanly).
  FINGERPRINT="${INSTANCE_NAME}|${LABELS}"
  if [ ! -f .runner ] || [ "$(cat .addon-config 2>/dev/null)" != "$FINGERPRINT" ]; then
    echo "Registering runner for ${REPO} ..."

    REG_TOKEN=$(curl -s -X POST \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${REPO}/actions/runners/registration-token" \
      | jq -r .token || true)

    if [ -z "$REG_TOKEN" ] || [ "$REG_TOKEN" = "null" ]; then
      echo "ERROR: Failed to get registration token for ${REPO}, skipping"
      continue
    fi

    CONFIG_ARGS=(
      --url "https://github.com/${REPO}"
      --token "$REG_TOKEN"
      --name "$INSTANCE_NAME"
      --work "$WORK_DIR"
      --unattended
      --replace
    )
    if [ -n "$LABELS" ] && [ "$LABELS" != "null" ]; then
      CONFIG_ARGS+=(--labels "$LABELS")
    fi

    if ! ./config.sh "${CONFIG_ARGS[@]}" 2>&1; then
      echo "ERROR: config.sh failed for ${REPO}, skipping"
      continue
    fi
    echo "$FINGERPRINT" > .addon-config
  else
    echo "Reusing existing registration for ${REPO}"
  fi

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
  wait
  echo "Cleanup done"
}

trap cleanup SIGTERM SIGINT

wait
