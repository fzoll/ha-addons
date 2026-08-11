#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"
NODE_ID=$(jq -r '.node_id' "$CONFIG_PATH")
ANTHROPIC_API_KEY_OPT=$(jq -r '.anthropic_api_key' "$CONFIG_PATH")

REPO_URL="https://github.com/fzoll/t3code.git"
BRANCH="fork/cc-runner-support"

# /data is the add-on's private volume: Home Assistant wipes it on uninstall.
# Everything that must survive a reinstall — T3 state (pairings, projects,
# threads), cloned workspaces, and provider CLI logins — lives under /share.
# The build tree stays in /data because it is fully reproducible from git.
PERSIST_DIR="/share/t3-code-runner"
SRC_DIR="/data/t3code-src"
T3_HOME="$PERSIST_DIR/t3"
SHARED_DIR="$PERSIST_DIR/SHARED"
HOME_DIR="$PERSIST_DIR/home"
BIN_PATH="$SRC_DIR/apps/server/dist/bin.mjs"
WEB_DIST="$SRC_DIR/apps/web/dist"
BUILT_SHA_FILE="$SRC_DIR/.built-sha"
PORT=3773

mkdir -p "$T3_HOME" "$SHARED_DIR" "$HOME_DIR"

# Migrate state left behind by add-on versions that stored everything in /data.
for legacy in t3 SHARED home; do
  if [ -d "/data/$legacy" ] && [ -z "$(ls -A "$PERSIST_DIR/$legacy" 2>/dev/null)" ]; then
    echo "Migrating /data/$legacy to $PERSIST_DIR/$legacy..."
    cp -a "/data/$legacy/." "$PERSIST_DIR/$legacy/"
  fi
done

# Claude Code (and any other provider CLI) stores its credentials under $HOME;
# point HOME at the persistent directory so logins survive reinstalls.
export HOME="$HOME_DIR"

# HA add-ons run as root. Claude Code refuses --dangerously-skip-permissions
# under root unless it can tell it is already inside a sandbox, and T3 Code
# always passes that flag for full-access sessions. The add-on container *is*
# the sandbox here, so declare it.
export IS_SANDBOX=1

if [ -n "$ANTHROPIC_API_KEY_OPT" ] && [ "$ANTHROPIC_API_KEY_OPT" != "null" ]; then
  export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_OPT"
fi

if [ ! -d "$SRC_DIR/.git" ]; then
  echo "Cloning t3code ($BRANCH)..."
  git clone --branch "$BRANCH" --depth=1 "$REPO_URL" "$SRC_DIR"
else
  echo "Updating t3code..."
  git -C "$SRC_DIR" fetch --depth=1 origin "$BRANCH"
  git -C "$SRC_DIR" reset --hard "origin/$BRANCH"
fi

REMOTE_SHA=$(git -C "$SRC_DIR" rev-parse HEAD)

# Building the full monorepo is expensive (mobile/desktop/web packages), so
# only rebuild when the source actually moved since the last successful build.
# The server serves the web client from apps/web/dist, so both must be built —
# without the web bundle every UI route answers "No static directory configured".
if [ ! -f "$BIN_PATH" ] || [ ! -d "$WEB_DIST" ] ||
  [ "$(cat "$BUILT_SHA_FILE" 2>/dev/null)" != "$REMOTE_SHA" ]; then
  echo "Building T3 Code server + web client for $REMOTE_SHA (first build can take a long time)..."
  cd "$SRC_DIR"
  vp i
  vp run --filter t3 build:bundle
  vp run --filter @t3tools/web build
  echo "$REMOTE_SHA" > "$BUILT_SHA_FILE"
else
  echo "T3 Code server already built for $REMOTE_SHA, skipping build."
fi

export T3CODE_HOME="$T3_HOME"

echo "Starting T3 Code server (node_id=$NODE_ID) on port $PORT..."
echo "First boot prints a 'Token: ...' pairing credential below — see DOCS.md to register this node with cc_runner."

exec node "$BIN_PATH" serve --port "$PORT" --host 0.0.0.0 --base-dir "$T3_HOME"
