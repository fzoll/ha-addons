# T3 Code Runner

Runs [T3 Code](https://github.com/fzoll/t3code) (fork `fzoll/t3code@fork/cc-runner-support`) as a
standalone, always-on agent harness server on this Home Assistant host, so it can act as a third
`cc_runner` executor node alongside the RPi (systemd) and Mac (Desktop app) nodes.

```
cc_runner (RPi) dispatch → T3 nodes: rpi / mac / ha-addon
                                              ↑
                                    This add-on: T3 Code server (port 3773)
                                    Workspace root: /share/t3-code-runner/SHARED
```

## What this add-on does

- Clones `fzoll/t3code` (branch `fork/cc-runner-support`) into `/data/t3code-src` and builds the
  `apps/server` package (`t3`) with the Vite+ toolchain. There is no published T3 Code Docker
  image, so it is always built from source.
- Starts the built server headless (`t3 serve --port 3773`) with its state directory at
  `/share/t3-code-runner/t3`.
- Installs the Claude Code CLI (`@anthropic-ai/claude-code`) — the provider T3 Code drives for
  `cc_runner` sessions — and points `$HOME` at `/share/t3-code-runner/home` so its login survives
  restarts *and* uninstalls.
- Installs the GitHub CLI (`gh`) and, when it is logged in, configures it as the global git
  credential helper on every boot. T3 Code shells out to plain `git` for fetch/push and supplies no
  credentials of its own, so without this every remote operation on a private https remote fails.
- Creates `/share/t3-code-runner/SHARED` as the workspace root. Point `workspaceRoot` at `/share/t3-code-runner/SHARED/<repo>`
  when creating T3 projects on this node so clones survive add-on restarts.
- Rebuilds only when the upstream fork's commit SHA changes (tracked in
  `/data/t3code-src/.built-sha`), since a full monorepo build is expensive.

## Requirements

- HA OS or Supervisor host with enough disk/RAM for a full Node.js monorepo build (the fork pulls
  in the web client packages that `apps/server` serves as static assets). The issue that requested
  this add-on assumes a 16GB RPi, where resources are not expected to be a constraint.
- Either set `anthropic_api_key` below, or authenticate Claude Code interactively once via
  `docker exec -it <container> claude auth login` (find the container name with `docker ps`; it is
  typically `addon_local_t3-code-runner` for a local add-on repo checkout).
- A GitHub login for any private repository this node clones or pushes to. Authenticate once:

  ```bash
  docker exec -it -e HOME=/share/t3-code-runner/home <container> gh auth login
  ```

  Both logins are stored under `/share`, so they persist across restarts and reinstalls. `run.sh`
  runs `gh auth setup-git` on every boot and warns in the add-on log when the login is missing.

## Configuration

| Option              | Description                                                                 |
|----------------------|-----------------------------------------------------------------------------|
| `node_id`            | Label this node registers under / pairs as (defaults to `ha`)               |
| `anthropic_api_key`  | Optional. If set, exported as `ANTHROPIC_API_KEY` so Claude Code works headlessly without an interactive `claude auth login`. |

## Registering with cc_runner

`cc_runner`'s `T3Client` (see `apps/server/src/services/t3-client.ts` in the `cc_runner` repo)
expects each node as a static entry:

```ts
{ id: "ha", host: "<this-host-tailscale-or-lan-ip>", port: 3773, tokenPath: "/path/on/cc_runner/host/to/ha.token", workspaceRoot: "/share/t3-code-runner/SHARED" }
```

There is currently no `cc_runner` API endpoint for a node to register itself dynamically (see
"What's left" below), so pairing is a one-time manual step, same as the RPi/Mac nodes:

1. **Start the add-on** and open its **Log** tab. On first boot (before any auth exists) it prints
   a pairing credential:
   ```
   T3 Code server is ready.
   Connection string: http://<ip>:3773
   Token: <PAIRING_TOKEN>
   Pairing URL: http://<ip>:3773/pair#token=<PAIRING_TOKEN>
   ```
   If you missed it or it expired, mint a new one on demand:
   ```bash
   docker exec -it <container> node /data/t3code-src/apps/server/dist/bin.mjs \
     auth pairing create --base-dir /share/t3-code-runner/t3 --ttl 60m --label cc-runner
   ```

2. **Exchange the token for an access token**, from wherever `cc_runner` runs:
   ```bash
   curl -sf -X POST "http://<ip>:3773/api/auth/bootstrap" \
     -H "Content-Type: application/json" \
     -d '{"credential":"<PAIRING_TOKEN>","clientLabel":"cc-runner","clientDeviceType":"server"}' \
     | jq -r '.accessToken' > /path/on/cc_runner/host/to/ha.token
   ```

3. **Add the node** to `cc_runner`'s `T3_NODES` config using the block above (`tokenPath` pointing
   at the file just written), and restart `cc_runner`.

4. **Verify**: `cc_runner` polls `GET http://<ip>:3773/.well-known/t3/environment` for health; it
   should report this node's `environmentId`, `label`, and free memory within a minute.

## What's left (not implemented here)

- **Dynamic node registration** (issue's preferred option): needs a new `cc_runner` API endpoint
  this add-on could call at startup. That endpoint doesn't exist upstream yet — out of scope for a
  Home Assistant add-on PR; tracked as a follow-up against `cc_runner`.
- **Phase 3 HA-specific features** (HA config validation tasks, automation testing, addon-build CI
  runner) — none of that exists yet; this add-on only stands up the generic T3 Code node.
- **End-to-end verification**: the build and pairing flow above is derived directly from the
  `t3code` fork's source (CLI flags, startup pairing output) and from `cc_runner`'s
  `T3CODE_INTEGRATION_SPEC.md`, but has not been run on real HA/Supervisor hardware in this
  environment (no Docker/Supervisor available here). Expect to iterate on the first real boot,
  particularly build time and disk usage for the full monorepo build.

## Pinned fork revision

`t3_revision` selects a full 40-character commit SHA from
`fzoll/t3code` branch `fork/cc-runner-support`. Restarting the add-on preserves
that selection; it does not automatically deploy a moving branch tip. New
installations default to the release's tested revision.

Before changing the revision, drain pipeline sessions and take a consistent
backup of T3 state. Change `t3_revision` in add-on configuration, restart, and
verify `serverVersion` through `/.well-known/t3/environment`. The build source
lives in `/data/t3code-src`; state, projects, and credentials remain in `/share`.
An earlier branch commit may be selected for rollback only after confirming
its database compatibility. Binary rollback does not undo database migrations.

## Credential publication helper (0.4.5)

The image supervises T3 and a separate credential publisher. The publisher uses
exactly the Node binary, compiled CLI and persistent `--base-dir` that start T3.
It checks every 300 seconds, renews within seven days of expiry, and reconciles
an already published generation without minting another token. Failed or timed
out publication never stops T3; each attempt is bounded to 90 seconds. Container
shutdown first stops the publisher, then allows T3 60 seconds to stop gracefully.
The supervisor forwards T3's exit status and reaps adopted child processes.

Publication is enabled by default but stays `unconfigured` until provisioned.
Set `credential_publish_enabled: false` to disable it. No credentials belong in
the image, repository, add-on options, command arguments, or logs.

Provision these files in `/share/t3-code-runner/credential-publish/` (directory
0700; files 0600), using a dedicated key for this node:

- `receiver.json`: only `environmentId`, `receiverHost`, `receiverUser`, and
  integer `receiverPort`. Obtain the environment ID from authenticated T3
  readiness and verify it against the registered cc_runner HA node.
- `id_ed25519`: private publication SSH key, not a general administration key.
- `known_hosts`: independently verified receiver host key; host checking is strict.

The receiver must use the reviewed `t3_credential_guard.py receive` protocol from
RPI_Hermes PR326. Its forced-command configuration pins this node's actual
registered token path, environment, and authenticated API base. Append a
`restrict,command="... receive --config ..."` public-key entry; never replace the
receiver's general authorized keys. Token payload travels over SSH stdin and
only a verified receiver ACK advances the local generation. Failed delivery
retains a private candidate for retry; lost ACKs reuse that same candidate.
Provider login credentials and existing sessions are not revoked or modified.

### Supervised rollout and rollback

Before upgrading: verify no active HA attempts, record the image and T3 commit,
and take a protected add-on/persistent-volume backup. This release keeps the T3
revision pin unchanged. Review and test the image before restarting the add-on.
Provision receiver restrictions and private volume files before the first
publication, then confirm `published` followed by `healthy` on reconciliation,
unchanged generation, and authenticated cc_runner readiness. Helper output alone
is not acceptance evidence. Keep the old image available for rollback.

If publication fails, disable the option and restart only when idle; the old
registered credential remains intact. Image rollback preserves the `/share` and
`/data` volumes. Remove any newly provisioned restricted public key only after
confirming rollback readiness. Never erase `.t3` data or provider login state.

The unit/fault suite exercises failed delivery, lost ACK, generation reuse,
revocation, unsafe configuration, helper failure/timeout, T3 exit propagation,
and log redaction. A successful suite does not assert that the ARM64 image or
live HA rollout has been verified.
