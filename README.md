# status-translations

*Translation-progress dashboard for the QuantEcon lecture series — public data store + GitHub Pages site tracking coverage, freshness, automation and review state for every language edition.*

**Live dashboard:** <https://quantecon.github.io/status-translations/>

This repo follows the org's `status-*` pattern (sibling of [status-lectures](https://github.com/QuantEcon/status-lectures), which tracks build/environment configuration): data lives in-repo as JSON, the dashboard is a static page on GitHub Pages, and no credentials beyond `GITHUB_TOKEN` are needed — every fact is computed from public GitHub state.

## What it answers

Translation health is two-dimensional: **coverage** (how much of the source series is translated) and **freshness** (how current those translations are against the moving English source). An edition can be 100% translated and rotting, or 65% and perfectly synced. The dashboard shows, per source series → edition:

- coverage (lectures translated / total, with per-lecture detail)
- last sync and upstream drift (source PRs merged since)
- automation wiring (sync / AI review / rebase workflows)
- human-review backlog (`translation-review` issues)
- a synthesised status (healthy / drifting / stalled / planned), plus the language-expansion pipeline

## How it works

1. `collector/collect.py` blobless-clones each source repo and its editions, compares `lectures/*.md` file sets and per-file last-commit dates, checks workflow wiring, and counts sync-era PRs and review issues.
2. It writes `data/latest.json` and a dated snapshot in `data/history/` — history accumulates from day one, so trend views come free later.
3. The site (static, no dependencies) fetches `data/latest.json` and renders three pages — **Overview** (stat tiles, series × edition table, language pipeline), **Rollout** (per-edition lifecycle steppers: scaffolded → seeded → automated → published → reviewed), and **Sync detail** (per-lecture cells + orphan files). The `publish` workflow deploys `site/` + `data/` to Pages on every push, and the `collect` workflow redeploys after committing fresh data. Every page carries a freshness badge (green ≤ 7 days since collection, orange past a week, red past two) and a light/dark theme toggle (system preference by default).

Editorial facts the collector can't compute (series titles, phase labels, review-campaign notes, the language pipeline) live in `collector/config.json`. To add a language or series, extend that file.

## Layout

```
data/
  latest.json         # current snapshot (the dashboard reads this)
  history/            # dated snapshots, append-only
site/
  index.html          # Overview page (static, client-side rendering)
  rollout.html        # Rollout tracker: per-edition lifecycle steppers
  sync.html           # Sync detail: per-lecture cells + orphan files
  style.css           # shared design system (light/dark themes)
  app.js              # shared chrome: nav, freshness badge, theme toggle, data loading
collector/
  collect.py          # computes the numbers (git + gh + python stdlib)
  config.json         # repo pairs + editorial fields
.github/workflows/
  publish.yml         # deploy site + data to Pages on push
  collect.yml         # nightly data collection (cron, 03:17 UTC) + redeploy
```

## Counting rule

A "lecture" is a top-level `lectures/*.md` file in the **source** repo, excluding `README` and `status` (the build-status page). Coverage counts files present in both source and edition; edition-only files are reported as **orphans** (e.g. pre-rename leftovers). Program docs have historically counted raw `.md` files including `status`, so figures here can sit one lower (48/51 vs 49/52) — this repo's rule is the canonical one for reporting.

## Status & verification

- The collector was **verified on 2026-07-18** against the hand-seeded 2026-07-09 snapshot: coverage and orphan lists reproduced exactly; the computed per-lecture staleness supersedes the seed's hand-set values. The nightly cron in `collect.yml` has been on since.
- Two measurement caveats, stated in the data itself (`last_sync_note`, `drift_approx`): the per-edition **activity date** is the newest commit touching a matched lecture file in the edition, so edition-local maintenance moves it too (read it as activity, not sync — per-lecture staleness is the reliable currency signal); and **drift-PR counts** are approximate by design (all merged source PRs since last activity, not only lecture-touching ones). The [translation-sync-metadata contract](https://github.com/QuantEcon/action-translation/issues/66) is the upgrade path to exact per-file drift.

## Placement (provisional)

This repo is the dashboard's **current** home, not a permanent commitment. How QuantEcon organises project and dashboard reporting is still being worked out (see the reporting-strategy discussions at [meta#332](https://github.com/QuantEcon/meta/issues/332) and [meta#321](https://github.com/QuantEcon/meta/issues/321)); if a central reporting hub emerges (e.g. under [QuantEcon/dashboard](https://github.com/QuantEcon/dashboard)), this dashboard is designed to relocate cheaply — the static site and the versioned data contract (`data/latest.json` + `data/history/`) are self-contained, so moving means moving files and updating one URL.

## Related repos

- [action-translation](https://github.com/QuantEcon/action-translation) — the translation engine (sync / review / rebase); its sync metadata (#66) is this dashboard's upgrade path for exact drift.
- [project-translation](https://github.com/QuantEcon/project-translation) — private program workspace: roadmap, decisions, research; this dashboard replaces its hand-maintained coverage tables as the live status layer.
- [status-lectures](https://github.com/QuantEcon/status-lectures) — build/environment-configuration dashboard for the same repo family.
- [dashboard](https://github.com/QuantEcon/dashboard) — curated presentation hub; links here for translation progress.
