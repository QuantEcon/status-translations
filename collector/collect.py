#!/usr/bin/env python3
"""Translation-progress collector (v1).

Compares each English source repo with its language editions and writes
data/latest.json plus a dated snapshot in data/history/. All facts are
computed from public GitHub state:

- coverage:   lectures/*.md present in both source and edition
- staleness:  per-file last-commit date, source vs edition
- last sync:  most recent commit touching lectures/ in the edition
- drift:      merged PRs in the source since the edition's last sync
              (all merged PRs, not only lecture-touching — an over-count,
              flagged as approximate in the data)
- automation: sync-translations-<lang>.yml in the source; review/rebase
              workflows in the edition
- review:     open issues labelled translation-review in the edition

Requires: git, gh (authenticated — GH_TOKEN in CI), python3.9+.
Status: v1 — verify a run against a hand audit before enabling the cron
(see README). Editorial fields (titles, phases, notes, pipeline) live in
collector/config.json; this script computes the numbers.
"""

import datetime as dt
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
ORG = "QuantEcon"


def sh(*cmd, cwd=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)
    return res.stdout.strip()


def clone(repo):
    """Blobless clone (full history metadata, no file contents up front)."""
    dest = WORK / repo
    if dest.exists():
        sh("git", "fetch", "--quiet", "origin", cwd=dest)
        sh("git", "reset", "--hard", "origin/HEAD", "--quiet", cwd=dest)
    else:
        WORK.mkdir(exist_ok=True)
        sh("git", "clone", "--quiet", "--filter=blob:none", "--single-branch",
           f"https://github.com/{ORG}/{repo}.git", str(dest))
    return dest


def lecture_slugs(dest, exclude):
    out = sh("git", "ls-files", "lectures/*.md", cwd=dest)
    slugs = []
    for line in out.splitlines():
        p = pathlib.PurePosixPath(line)
        if len(p.parts) == 2:  # top-level lectures/*.md only
            slug = p.stem
            if slug not in exclude:
                slugs.append(slug)
    return sorted(slugs)


def last_commit_date(dest, path):
    out = sh("git", "log", "-1", "--format=%cI", "--", path, cwd=dest, check=False)
    return dt.datetime.fromisoformat(out) if out else None


def has_workflow(dest, name):
    return (WORK / dest / ".github" / "workflows" / name).exists()


def merged_prs_since(repo, iso_date):
    out = sh("gh", "pr", "list", "-R", f"{ORG}/{repo}", "--state", "merged",
             "--limit", "200", "--search", f"merged:>={iso_date}",
             "--json", "number", check=False)
    try:
        return len(json.loads(out))
    except (json.JSONDecodeError, TypeError):
        return None


def open_review_issues(repo):
    out = sh("gh", "issue", "list", "-R", f"{ORG}/{repo}", "--state", "open",
             "--label", "translation-review", "--limit", "200",
             "--json", "number", check=False)
    try:
        return len(json.loads(out))
    except (json.JSONDecodeError, TypeError):
        return 0


def age_label(date):
    days = (dt.datetime.now(dt.timezone.utc) - date).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def collect_edition(cfg_src, cfg_ed, src_dest, exclude, stalled_after):
    tgt_dest = clone(cfg_ed["target_repo"])
    src_slugs = lecture_slugs(src_dest, exclude)
    tgt_slugs = set(lecture_slugs(tgt_dest, exclude))

    lectures, stale = [], 0
    for slug in src_slugs:
        if slug not in tgt_slugs:
            lectures.append({"slug": slug, "state": "missing"})
            continue
        s_date = last_commit_date(src_dest, f"lectures/{slug}.md")
        t_date = last_commit_date(tgt_dest, f"lectures/{slug}.md")
        if s_date and t_date and s_date > t_date:
            lectures.append({"slug": slug, "state": "stale"})
            stale += 1
        else:
            lectures.append({"slug": slug, "state": "fresh"})
    translated = sum(1 for c in lectures if c["state"] != "missing")
    orphans = sorted(tgt_slugs - set(src_slugs))

    sync_dates = [d for slug in src_slugs if slug in tgt_slugs
                  if (d := last_commit_date(tgt_dest, f"lectures/{slug}.md"))]
    last_sync = max(sync_dates) if sync_dates else None
    drift = merged_prs_since(cfg_src["repo"], last_sync.date().isoformat()) if last_sync else None

    wired = has_workflow(cfg_src["repo"], f"sync-translations-{cfg_ed['lang']}.yml")
    parts = ("sync" + (" · AI review" if has_workflow(cfg_ed["target_repo"], "review-translations.yml") else "")
             + (" · rebase" if has_workflow(cfg_ed["target_repo"], "rebase-translations.yml") else "")) if wired \
        else cfg_ed.get("automation_note", "not wired")

    days_since = (dt.datetime.now(dt.timezone.utc) - last_sync).days if last_sync else None
    if wired and stale == 0 and translated == len(src_slugs):
        status, label = "healthy", cfg_ed.get("status_label_healthy", "Healthy")
    elif days_since is not None and days_since > stalled_after:
        status, label = "stalled", "Stalled"
    else:
        status, label = "drifting", "Drifting"

    return {
        "lang": cfg_ed["lang"], "lang_label": cfg_ed["lang_label"],
        "target_repo": cfg_ed["target_repo"],
        "lectures_translated": translated, "freshness": "computed", "stale": stale,
        "last_sync": {"date": last_sync.date().isoformat() if last_sync else None,
                      "lag": age_label(last_sync) if last_sync else "never"},
        "drift_prs": drift, "drift_approx": True,
        "automation": {"wired": wired, "parts": parts},
        "review": {"open": open_review_issues(cfg_ed["target_repo"]),
                   "note": cfg_ed.get("review_note", "")},
        "status": status, "status_label": label,
        "orphans": orphans, "lectures": lectures,
    }


def main():
    config = json.loads((ROOT / "collector" / "config.json").read_text())
    exclude = set(config["exclude_files"])
    today = dt.date.today().isoformat()

    sources = []
    for cfg_src in config["sources"]:
        if cfg_src.get("phase"):
            sources.append({"repo": cfg_src["repo"], "title": cfg_src["title"],
                            "lectures_total": cfg_src["lectures_total"],
                            "phase": cfg_src["phase"], "editions": cfg_src["editions"]})
            continue
        src_dest = clone(cfg_src["repo"])
        total = len(lecture_slugs(src_dest, exclude))
        editions = [collect_edition(cfg_src, e, src_dest, exclude, config["stalled_after_days"])
                    for e in cfg_src["editions"]]
        sources.append({"repo": cfg_src["repo"], "title": cfg_src["title"],
                        "lectures_total": total, "editions": editions})

    data = {
        "schema_version": 1,
        "generated_at": today,
        "collected_by": "collector v1 (collect.py)",
        "counting_rule": ("lectures/*.md in the source repo, excluding "
                          + "/".join(sorted(exclude))
                          + "; coverage = files present in both source and edition"),
        "sources": sources,
        "pipeline": config["pipeline"],
    }
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "data" / "latest.json").write_text(payload)
    (ROOT / "data" / "history" / f"{today}.json").write_text(payload)
    print(f"wrote data/latest.json + data/history/{today}.json")


if __name__ == "__main__":
    main()
