#!/usr/bin/env bash
set -euo pipefail
SRC_DIR=$1
REPO_URL=$2
BRANCH=$3
REVISION=$4
[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid commit SHA" >&2; exit 1; }
if [ ! -d "$SRC_DIR/.git" ]; then
  git init "$SRC_DIR"
  git -C "$SRC_DIR" remote add origin "$REPO_URL"
fi

# Fetch the full fork history so reachability is meaningful, including rollbacks.
# Never use an arbitrary upstream release in place of the fork's integrations.
FETCH_ARGS=()
if [ "$(git -C "$SRC_DIR" rev-parse --is-shallow-repository)" = "true" ]; then
  FETCH_ARGS+=(--unshallow)
fi
git -C "$SRC_DIR" fetch --no-tags "${FETCH_ARGS[@]}" origin "$BRANCH"
git -C "$SRC_DIR" merge-base --is-ancestor "$REVISION" FETCH_HEAD || {
  echo "Requested revision is not part of $BRANCH; refusing to start." >&2
  exit 1
}
# Only the reproducible build tree is reset; persistent user data is separate.
git -C "$SRC_DIR" reset --hard "$REVISION"

