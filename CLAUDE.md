# ha-addons — Claude Code szabályok

Home Assistant addon store repo (cc-runner, github-runner). A HA Supervisor
auto-update figyeli — **egy addon frissítése CSAK akkor jut el a HA gépre, ha a
verziója nő.**

## KÖTELEZŐ: verzió-bump minden addon-változásnál

Ha egy addon könyvtárában (cc-runner/, github-runner/) BÁRMI változik, a PR-ben
KÖTELEZŐ az adott addon `config.yaml` `version` mezőjét bumpolni (patch szint elég,
pl. 0.1.2 → 0.1.3), és a commit üzenet címében jelezni: `fix(cc-runner): ... (0.1.3)`.
Verzió-bump nélkül a Supervisor SOSEM telepíti a változást — a fix halott betű marad.

## Review checklist

- Addon-fájl változott? → version bump megvan?
- CHANGELOG.md frissítve (ha létezik az addonban)?
