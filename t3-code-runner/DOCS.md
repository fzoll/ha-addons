# T3 Code Runner

Runs [T3 Code](https://github.com/fzoll/t3code) (fork `fzoll/t3code@fork/cc-runner-support`) as a
standalone, always-on agent harness server on this Home Assistant host, so it can act as a third
`cc_runner` executor node alongside the RPi (systemd) and Mac (Desktop app) nodes.

```
cc_runner (RPi) dispatch → T3 nodes: rpi / mac / ha-addon
                                              ↑
                                    This add-on: T3 Code server (port 3773)
                                    Workspace root: /data/SHARED
```

## What this add-on does

- Clones `fzoll/t3code` (branch `fork/cc-runner-support`) into `/data/t3code-src` and builds the
  `apps/server` package (`t3`) with the Vite+ toolchain. There is no published T3 Code Docker
  image, so it is always built from source.
- Starts the built server headless (`t3 serve --port 3773`) with its state directory at `/data/t3`.
- Installs the Claude Code CLI (`@anthropic-ai/claude-code`) — the provider T3 Code drives for
  `cc_runner` sessions — and points `$HOME` at `/data/home` so its login persists across restarts.
- Creates `/data/SHARED` as the workspace root. Point `workspaceRoot` at `/data/SHARED/<repo>`
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

## Configuration

| Option              | Description                                                                 |
|----------------------|-----------------------------------------------------------------------------|
| `node_id`            | Label this node registers under / pairs as (defaults to `ha`)               |
| `anthropic_api_key`  | Optional. If set, exported as `ANTHROPIC_API_KEY` so Claude Code works headlessly without an interactive `claude auth login`. |

## Registering with cc_runner

`cc_runner`'s `T3Client` (see `apps/server/src/services/t3-client.ts` in the `cc_runner` repo)
expects each node as a static entry:

```ts
{ id: "ha", host: "<this-host-tailscale-or-lan-ip>", port: 3773, tokenPath: "/path/on/cc_runner/host/to/ha.token", workspaceRoot: "/data/SHARED" }
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
     auth pairing create --base-dir /data/t3 --ttl 60m --label cc-runner
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
