# ha-addons — Claude Code szabályok

Home Assistant addon store repo (cc-runner, github-runner, t3-code-runner, ncore-streamer). A HA Supervisor
auto-update figyeli — **egy addon frissítése CSAK akkor jut el a HA gépre, ha a
verziója nő.**

## KÖTELEZŐ: verzió-bump minden addon-változásnál

Ha egy addon könyvtárában (cc-runner/, github-runner/, t3-code-runner/, ncore-streamer/) BÁRMI változik, a PR-ben
KÖTELEZŐ az adott addon `config.yaml` `version` mezőjét bumpolni (patch szint elég,
pl. 0.1.2 → 0.1.3), és a commit üzenet címében jelezni: `fix(cc-runner): ... (0.1.3)`.
Verzió-bump nélkül a Supervisor SOSEM telepíti a változást — a fix halott betű marad.

## ncore-streamer: automatikus pin-bump

Az `ncore-streamer/` add-on a privát `fzoll/ncore-streamer` repó egy pinelt commitját
(`ncore-streamer/REVISION`) klónozza futásidőben. A pin-bump PR-eket (`bot/ncore-streamer-<sha7>`,
`fix(ncore-streamer): pin <sha7> (<verzió>)`) a `.github/workflows/ncore-streamer-bump.yml`
workflow nyitja óránként — kézzel ne bumpold a `REVISION`-t, és ne tedd option-be (a HA a
telepített add-on optionjeit megtartja). A workflowhoz kell a `NCORE_STREAMER_DEPLOY_KEY` secret és
a repó *Settings → Actions → General → Allow GitHub Actions to create and approve pull requests*
beállítás (különben a `gh pr create` hibázik). A workflow a PR-t maga merge-öli (`gh pr merge --squash --delete-branch`), kézi lépés nincs
(legfeljebb a HA Update, ha az add-onon nincs auto-update).

## Review checklist

- Addon-fájl változott? → version bump megvan?
- CHANGELOG.md frissítve (ha létezik az addonban)?
