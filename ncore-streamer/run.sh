#!/usr/bin/env bash
set -euo pipefail

OPTIONS_PATH="/data/options.json"
REPO_URL="git@github.com:fzoll/ncore-streamer.git"
BRANCH="master"
REVISION=$(tr -d '[:space:]' < /REVISION)
if [[ ! "$REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid REVISION: expected a full lowercase Git commit SHA." >&2
  exit 1
fi

# /data is wiped on uninstall: only reproducible things live there (deploy key,
# source clone, venv). The database and media live under /share.
KEY_PATH="/data/deploy_key"
SRC_DIR="/data/src"
VENV_DIR="/data/venv"
PERSIST_DIR="/share/ncore-streamer"
PORT=9876

# --- Deploy key -------------------------------------------------------------
if [ ! -f "$KEY_PATH" ]; then
  echo "Generating deploy key..."
  rm -f "$KEY_PATH" "$KEY_PATH.pub"
  ssh-keygen -q -t ed25519 -N '' -C "ncore-streamer-addon" -f "$KEY_PATH"
fi
chmod 600 "$KEY_PATH"
# Re-derive the public half so it is always available, even if it was lost.
ssh-keygen -y -f "$KEY_PATH" > "$KEY_PATH.pub"
# Public key only; the private key must never reach the log.
echo "NCORE_DEPLOY_PUBLIC_KEY: $(cut -d' ' -f1,2 "$KEY_PATH.pub")"

export GIT_SSH_COMMAND="ssh -i $KEY_PATH -o IdentitiesOnly=yes -o UserKnownHostsFile=/data/known_hosts -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
export GIT_TERMINAL_PROMPT=0

# --- Clone / fetch the pinned revision ---------------------------------------
if [ ! -d "$SRC_DIR/.git" ]; then
  git init -q "$SRC_DIR"
  git -C "$SRC_DIR" remote add origin "$REPO_URL"
fi
git -C "$SRC_DIR" remote set-url origin "$REPO_URL"

FETCH_ARGS=()
if [ "$(git -C "$SRC_DIR" rev-parse --is-shallow-repository)" = "true" ]; then
  FETCH_ARGS+=(--unshallow)
fi
# Full history so reachability is meaningful, including rollbacks.
if ! FETCH_OUT=$(git -C "$SRC_DIR" fetch --no-tags "${FETCH_ARGS[@]}" origin "$BRANCH" 2>&1); then
  echo "$FETCH_OUT" >&2
  if grep -qiE 'permission denied|publickey|could not read from remote|repository not found|host key verification' <<< "$FETCH_OUT"; then
    echo "ERROR: cannot read fzoll/ncore-streamer. Add the public key above (NCORE_DEPLOY_PUBLIC_KEY) as a read-only deploy key on fzoll/ncore-streamer." >&2
  fi
  exit 1
fi
git -C "$SRC_DIR" merge-base --is-ancestor "$REVISION" FETCH_HEAD || {
  echo "Pinned revision is not part of $BRANCH; refusing to start." >&2
  exit 1
}
git -C "$SRC_DIR" reset --hard "$REVISION"
echo "Running ncore-streamer at $REVISION"

# --- Virtualenv --------------------------------------------------------------
REQ_HASH=$(sha256sum "$SRC_DIR/requirements.txt" | cut -d' ' -f1)
if [ ! -x "$VENV_DIR/bin/python" ] || [ "$(cat "$VENV_DIR/.requirements-sha256" 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "Installing Python dependencies..."
  rm -rf "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --no-cache-dir -r "$SRC_DIR/requirements.txt"
  echo "$REQ_HASH" > "$VENV_DIR/.requirements-sha256"
fi

# --- App config from HA options ----------------------------------------------
# The app reads config.yaml from its working directory.
"$VENV_DIR/bin/python" - "$OPTIONS_PATH" "$SRC_DIR/config.yaml" <<'PY'
import json
import sys

import yaml

opts = json.load(open(sys.argv[1]))

config = {
    'ncore': {
        'username': opts['ncore_username'],
        'password': opts['ncore_password'],
    },
    'anthropic': {
        'api_key': '',
        'model': '',
    },
    'jellyfin': {
        'url': opts['jellyfin_url'],
        'api_key': opts['jellyfin_api_key'],
    },
    'transmission': {
        'url': opts['transmission_url'],
        'download_prefix': '/share/ncore-streamer',
    },
    'tmdb': {
        'api_key': opts['tmdb_api_key'],
    },
    'media': {
        'movies_path': '/share/ncore-streamer/movies',
        'movies_4k_path': '/share/ncore-streamer/movies-4k',
        'torrents_path': '/share/ncore-streamer/torrents',
        'downloads_path': '/share/ncore-streamer/downloads',
        'videos_path': '/share/ncore-streamer/videos',
        'db_path': '/share/ncore-streamer/ncore-streamer.db',
    },
    'sync': {
        'interval_hours': opts.get('sync_interval_hours', 4),
        'pages_per_category': opts.get('pages_per_category', 5),
        'min_seeders': opts.get('min_seeders', 5),
    },
    'cleanup': {
        'max_age_days': opts.get('cleanup_max_age_days', 7),
        'disk_usage_threshold': 0.8,
        'schedule': opts.get('cleanup_schedule', '04:00'),
    },
    'server': {
        'port': 9876,
    },
}

with open(sys.argv[2], 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
print('Config generated from HA options')
PY
chmod 600 "$SRC_DIR/config.yaml"

mkdir -p "$PERSIST_DIR/movies" "$PERSIST_DIR/movies-4k" "$PERSIST_DIR/torrents" \
  "$PERSIST_DIR/downloads" "$PERSIST_DIR/videos"

cd "$SRC_DIR"
exec "$VENV_DIR/bin/python" -m uvicorn ncore_streamer.main:create_app --factory \
  --app-dir "$SRC_DIR" --host 0.0.0.0 --port "$PORT" --log-level info
