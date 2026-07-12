# GitHub Actions Runner

Self-hosted GitHub Actions runner running as a Home Assistant add-on.
One runner instance is started for each configured repository.

## Security warning

**Never connect this runner to a public repository.** Anyone who can open a
pull request could execute arbitrary code on your Home Assistant machine.
Use private repositories only, or restrict Actions in the repository settings
so that workflows from forks cannot run on self-hosted runners.

## Setup

1. Create a GitHub personal access token that can register runners:
   - **Fine-grained token (recommended):** scope it to the target
     repositories with *Administration: Read and write* and
     *Metadata: Read* permissions.
   - **Classic token:** `repo` scope (grants access to all your
     repositories — prefer fine-grained).
2. Install the add-on and open the **Configuration** tab:

   ```yaml
   access_token: github_pat_xxx
   repos:
     - owner/repo
   runner_name: ha-runner
   labels: ""
   ```

3. Start the add-on. The log should show
   `Registering runner for owner/repo ...` followed by
   `All runners started`.
4. In your workflow:

   ```yaml
   runs-on: self-hosted
   ```

## Options

| Option | Description |
|--------|-------------|
| `access_token` | GitHub token used to fetch runner registration tokens. Only needed at first registration per repository. |
| `repos` | List of `owner/repo` entries. One runner is started per repository. |
| `runner_name` | Base name; the runner appears as `<runner_name>-<owner>-<repo>`. |
| `labels` | Extra comma-separated labels. Leave empty — the runner automatically gets `self-hosted`, `linux` and its architecture (`X64`/`ARM64`) as labels. |

## Notes

- Registration is persisted in `/data`, so restarts do not re-register and
  keep working even if the access token expires later.
- To force a fresh registration (e.g. after renaming), stop the add-on,
  remove the runner on GitHub under *Settings → Actions → Runners*, then
  rebuild/reinstall the add-on or clear its data.
- The runner self-updates automatically when GitHub releases a new version.
