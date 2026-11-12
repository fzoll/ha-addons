# T3 Code Runner

Runs the official, unmodified [T3 Code](https://github.com/pingdotgg/t3code) server on this Home
Assistant host, so the machine can work as an always-on T3 Code environment next to your other
machines.

Up to add-on version 0.4.x this add-on built a fork of T3 Code from source. Since 0.5.0 it installs
a pinned official release instead.

## What this add-on does

- Installs a pinned official T3 Code release (see `T3_VERSION` in the `Dockerfile`) from the
  project's GitHub releases, verified against the release checksum. Nothing is built from source.
- Starts the server with `t3 serve --host 0.0.0.0 --port 3773`, with its data directory at
  `/share/t3-code-runner/t3-home`.
- Links the environment to T3 Connect on first start (optional, see below).
- Installs the Claude Code CLI (`@anthropic-ai/claude-code`) and points `$HOME` at
  `/share/t3-code-runner/home`, so provider logins survive restarts and uninstalls.
- Installs the Codex CLI (`@openai/codex`, pinned by `CODEX_VERSION` in the `Dockerfile`) next to
  Claude Code, so T3 Code can use Codex as a provider.
- Installs the GitHub CLI (`gh`) and, when it is logged in, configures it as the global git
  credential helper on every boot. T3 Code uses plain `git` for fetch and push and supplies no
  credentials of its own.
- Installs `cloudflared` in the version this T3 release expects. T3 Connect needs it, and T3 Code
  can only download it through an interactive prompt that an add-on cannot answer.
- Uses `/share/t3-code-runner/SHARED` as the working directory. Clone repositories there so they
  survive add-on restarts and reinstalls.

## Configuration

| Option              | Description |
|---------------------|-------------|
| `t3_connect`        | Default `true`. Link this environment to your T3 Connect account on start. Set to `false` to reach the server only over the local network or Tailscale. |
| `anthropic_api_key` | Optional. If set, exported as `ANTHROPIC_API_KEY` so Claude Code works without an interactive `claude auth login`. |

## First start

### T3 Connect

With `t3_connect` on and the environment not linked yet, the add-on log shows a sign-in address and
a short code:

```
Sign in to T3 Connect. Open on any device:
  https://accounts.t3.codes/device?user_code=...
Code: XXXX-XXXX
Waiting for approval. Expires in 10 min.
```

Open the address on any device and approve it with your T3 Connect account. The server starts as
soon as you approve. If nobody approves within 10 minutes the server starts without T3 Connect;
restart the add-on to get a new code.

The link is stored in `/share/t3-code-runner/t3-home` and is reused on every later start. Do not
delete that directory: a new one counts as a new machine on your T3 Connect account, and the old
one keeps occupying a slot until you deregister it on the account's T3 Connect page.

### Provider and GitHub logins

Find the container name with `docker ps` (typically `addon_local_t3-code-runner` or
`addon_<repo-hash>_t3-code-runner`), then:

```bash
docker exec -it -e HOME=/share/t3-code-runner/home <container> claude auth login
docker exec -it -e HOME=/share/t3-code-runner/home <container> codex login --device-auth
docker exec -it -e HOME=/share/t3-code-runner/home <container> gh auth login
```

Codex needs device code sign-in to be enabled for your ChatGPT account first, at
<https://chatgpt.com/#settings/Security>; without it `codex login --device-auth` is refused. The
command prints a URL and a code: open the URL on any device and enter the code. The Codex login is
stored in `~/.codex`, that is `/share/t3-code-runner/home/.codex`.

All logins are stored under `/share`, so they persist across restarts and reinstalls. `run.sh`
warns in the add-on log when the GitHub login is missing.

## Upgrading T3 Code

All machines that work together must run the same T3 Code version. To move this add-on to a new
release, change these in one pull request:

1. `T3_VERSION` and both `T3_SHA256_*` values in the `Dockerfile` (from the release's `SHA256SUMS`).
2. `CLOUDFLARED_VERSION` and its checksums, if the new T3 release expects another version
   (`t3 connect status --json` reports it as `relayClient.version`).
3. `CODEX_VERSION` in the `Dockerfile`, to move Codex to a new release.
4. `version` in `config.yaml` — Home Assistant only installs a change when the version grows.

## State from add-on versions before 0.5.0

The fork's data directory, `/share/t3-code-runner/t3`, is not used any more and is not deleted.
The official release cannot open it. Remove it by hand once you no longer need the old thread
history. The same goes for `/share/t3-code-runner/credential-publish` and the
`activation-*` files, which belonged to the retired cc_runner integration.

Options from older versions (`node_id`, `t3_revision`, `credential_publish_enabled`) are no longer
read.

## Notes

- Home Assistant add-ons run as root. The add-on sets `IS_SANDBOX=1` so Claude Code accepts
  full-access sessions, and `T3CODE_SERVER_BROWSER_SANDBOX=0` because T3's built-in browser cannot
  start its own sandbox as root. The add-on container is the isolation boundary.
- Port 3773 is published on the host. T3 Code still requires pairing or a T3 Connect sign-in before
  it accepts a client.
