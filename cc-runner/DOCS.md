# CC Runner Agent

Connects this Home Assistant host to a [CC Runner](https://github.com/fzoll/cc_runner) server as a
runner agent. The add-on receives task offers over WebSocket and executes Claude Code sessions in
isolated Docker containers on the host, alongside standalone runners on RPi/Mac/Cloud.

## Requirements

- A running CC Runner server, reachable from this host.
- A runner token issued by the server admin via `POST /api/runner-tokens`.
- Home Assistant OS or Supervisor with Docker (the add-on needs `docker_api: true` to spawn
  executor containers).
- **Protection mode must be disabled** on the add-on's Info page. `docker_api: true` alone
  grants read-only Docker access; pulling the executor image and starting containers are
  write operations and fail silently without this.

## Executor image

The agent pulls `executor_image` from ghcr.io on demand (and re-pulls after self-updates).
If the package is private, store a GitHub token with `read:packages` scope in the CC Runner
server vault under the key `ghcr_token` — the agent fetches it with its runner token. If the
package is public, no token is needed. The published image must match this host's
architecture (aarch64/amd64).

## Configuration

| Option           | Description                                                                 |
|-------------------|-----------------------------------------------------------------------------|
| `server_url`      | Base URL of the CC Runner server, e.g. `https://cc-runner.example.com`     |
| `runner_token`    | Token issued by the CC Runner server admin                                  |
| `runner_name`     | Name this runner registers under (defaults to `ha-runner`)                  |
| `max_slots`       | Maximum number of concurrent tasks (1-8)                                    |
| `executor_image`  | Docker image used to run tasks (defaults to the published `cc-executor`)    |
| `gh_token`        | GitHub token with read access to `fzoll/cc_runner` (private repo)           |

If `gh_token` is left blank, the add-on fetches it from the CC Runner server's secret vault
(`GET /api/runner/secrets/gh_token:fzoll`) using the configured `runner_token`.

## How it works

On startup, the add-on clones (or updates) `fzoll/cc_runner` into `/data/cc_runner`, builds the
runner package, and starts it. Task results pending delivery to the server are buffered in
`/data/pending` and survive add-on restarts. The source is fetched and rebuilt on every start;
`/data` persistence only saves the initial clone.
