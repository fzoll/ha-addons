# nCore Streamer

Syncs the nCore torrent catalog with Jellyfin and Transmission; browse and stream movies via the
ingress panel (port 9876).

The app code lives in the **private** repo `fzoll/ncore-streamer`. This add-on contains no app code:
at every start `run.sh` clones the commit pinned in the add-on's `REVISION` file into `/data/src`
using a read-only deploy key, installs the dependencies into `/data/venv` (reinstalled only when
`requirements.txt` changes) and starts uvicorn.

## Installation

1. Install and start the add-on. The first start fails with a clear error — that is expected.
2. Open the add-on log and copy the line `NCORE_DEPLOY_PUBLIC_KEY: ssh-ed25519 ...`.
3. On GitHub: `fzoll/ncore-streamer` → Settings → Deploy keys → Add deploy key. Paste the key,
   leave **Allow write access** unchecked.
4. Fill in the options below and start the add-on again.

The key pair is generated once in `/data/deploy_key` and the public half is printed on every start.
The private key is never logged. Uninstalling the add-on deletes the key; a reinstall generates a new
one that must be registered again (remove the old deploy key from GitHub).

## Configuration

| Option                 | Description                                  |
|------------------------|----------------------------------------------|
| `ncore_username`       | nCore login                                  |
| `ncore_password`       | nCore password                               |
| `jellyfin_url`         | Jellyfin base URL                            |
| `jellyfin_api_key`     | Jellyfin API key                             |
| `transmission_url`     | Transmission RPC URL                         |
| `tmdb_api_key`         | TMDB API key                                 |
| `sync_interval_hours`  | Catalog sync interval                        |
| `pages_per_category`   | nCore pages fetched per category             |
| `min_seeders`          | Minimum seeders for a torrent to be listed   |
| `cleanup_max_age_days` | Age after which downloads are cleaned up     |
| `cleanup_schedule`     | Daily cleanup time (`HH:MM`)                 |

There is deliberately no revision option: Home Assistant keeps the options of an installed add-on,
so a new default would never apply. The pin is the `REVISION` file shipped with the add-on.

## Where data lives

| Path                                    | Content                                  | Survives uninstall |
|-----------------------------------------|------------------------------------------|--------------------|
| `/share/ncore-streamer/ncore-streamer.db` | SQLite database                        | yes                |
| `/share/ncore-streamer/{movies,movies-4k,torrents,downloads,videos}` | media, torrents | yes |
| `/data/deploy_key`, `/data/src`, `/data/venv` | deploy key, source clone, virtualenv | no (reproducible) |

## Updating

A GitHub Actions workflow (`ncore-streamer-bump.yml`) checks `fzoll/ncore-streamer` `master` every
hour. When it moved, it opens a PR that updates `ncore-streamer/REVISION` and bumps the add-on
patch version. Merge the PR, then press **Update** on the add-on in Home Assistant. The workflow
needs the repository secret `NCORE_STREAMER_DEPLOY_KEY` (a read-only deploy key of
`fzoll/ncore-streamer`, set by the operator).

The `REVISION` must be an ancestor of `master`; otherwise the add-on refuses to start.
