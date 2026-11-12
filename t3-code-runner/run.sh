#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"
T3_CONNECT=$(jq -r 'if has("t3_connect") then .t3_connect else true end' "$CONFIG_PATH")
ANTHROPIC_API_KEY_OPT=$(jq -r '.anthropic_api_key // ""' "$CONFIG_PATH")

# /data is the add-on's private volume: Home Assistant wipes it on uninstall.
# Everything that must survive a reinstall — T3 state (environment identity,
# T3 Connect link, projects, threads), cloned repositories, and provider CLI
# logins — lives under /share.
PERSIST_DIR="/share/t3-code-runner"
# Add-on versions before 0.5.0 ran a fork of T3 Code and kept its state in
# $PERSIST_DIR/t3. The official release cannot open that database (its
# migration history differs), so the official server gets its own directory
# and the old one is left untouched for manual cleanup.
T3_HOME="$PERSIST_DIR/t3-home"
SHARED_DIR="$PERSIST_DIR/SHARED"
HOME_DIR="$PERSIST_DIR/home"
PORT=3773

mkdir -p "$T3_HOME" "$SHARED_DIR" "$HOME_DIR"

# Claude Code (and any other provider CLI) stores its credentials under $HOME;
# point HOME at the persistent directory so logins survive reinstalls.
export HOME="$HOME_DIR"
export T3CODE_HOME="$T3_HOME"

# HA add-ons run as root. Claude Code refuses --dangerously-skip-permissions
# under root unless it can tell it is already inside a sandbox, and T3 Code
# passes that flag for full-access sessions. The add-on container *is* the
# sandbox here, so declare it.
export IS_SANDBOX=1

# T3's built-in browser cannot start its own sandbox as root either.
export T3CODE_SERVER_BROWSER_SANDBOX=0

if [ -n "$ANTHROPIC_API_KEY_OPT" ] && [ "$ANTHROPIC_API_KEY_OPT" != "null" ]; then
  export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_OPT"
fi

# T3 Code drives plain `git` for fetch/push against https remotes and never
# supplies credentials itself. `gh auth setup-git` is idempotent and only needs
# the login state, which lives under the persistent $HOME.
if [ -f "$HOME/.config/gh/hosts.yml" ]; then
  gh auth setup-git
  echo "GitHub CLI credential helper configured for $(gh api user --jq .login 2>/dev/null || echo 'unknown user')."
else
  echo "WARNING: GitHub CLI is not logged in — git fetch/push against private https remotes will fail."
  echo "         Run: docker exec -it -e HOME=$HOME_DIR <container> gh auth login"
fi

echo "T3 Code $(t3 --version 2>/dev/null | tail -1), data directory $T3_HOME"

# T3 Connect has to be authorized before the server starts. Without a terminal
# the CLI prints a URL and a short code and waits up to 10 minutes for the
# approval; both appear in this add-on's log. If nobody approves in time the
# server starts anyway and the next add-on restart asks again.
if [ "$T3_CONNECT" = "true" ]; then
  if [ "$(t3 connect status --json 2>/dev/null | jq -r '.linked // false' 2>/dev/null)" = "true" ]; then
    echo "T3 Connect: this environment is already linked."
  else
    echo "T3 Connect: not linked yet. Approve the sign-in below from any device."
    if t3 connect link --headless; then
      echo "T3 Connect: linked."
    else
      echo "WARNING: T3 Connect was not linked (no approval within the time limit, or sign-in failed)."
      echo "         Starting the server without it. Restart the add-on to try again."
    fi
  fi
fi

# T3 probes every provider CLI once when the server starts (and again only when
# that provider's settings change). On a Raspberry Pi the first launch of a
# freshly installed binary is slow enough for that probe to time out, leaving
# the provider marked "Provider executable is not installed" until someone
# forces a re-probe. Run each CLI once here so the slow first start happens
# before T3's probe. A failure or hang must never block the server start.
for provider_cli in claude codex; do
  if provider_version=$(timeout 120 "$provider_cli" --version 2>&1); then
    echo "Provider CLI $provider_cli: $(echo "$provider_version" | tail -1)"
  else
    echo "WARNING: '$provider_cli --version' failed or timed out; starting the server anyway."
  fi
done

cd "$SHARED_DIR"
echo "Starting T3 Code server on port $PORT..."
exec t3 serve --host 0.0.0.0 --port "$PORT" --base-dir "$T3_HOME" --no-browser
