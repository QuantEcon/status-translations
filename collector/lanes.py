#!/usr/bin/env python3
"""Review-lane computation (WS8 render half — status-translations#3).

Derives the Stage 4 routing lanes from the verdict event store
(data/verdicts.jsonl, captured nightly by verdicts.py) joined with live
open-PR state. Everything is keyed on `recommendation`, which exists on
every verdict — not on `wouldAutoMerge`, which is shadow-only and null
across most of the corpus (44 of the first 47 verdicts ran under mode
`off`). Where both are present, wouldAutoMerge is surfaced as
confirmation that the gate agrees with the rubric, never as the signal.

Fail-closed: events with parse != "ok" contribute nothing; a repo with no
events reports zero verdicts and the pages render "no verdicts yet",
never a default. Superseded verdicts (re-review) are excluded — the
current verdict per PR is the latest non-superseded event.

The primary-editor field reads `editors:` from the edition's
.translate/config.yml once the QuantEcon/project-translation#24 rollout
lands; until then it is null, and editions with routed-open PRs flag red
on the dashboard — which is the truthful state (project-translation#19).
The per-lecture in-review overlay derives from open editor-routed PR file
lists; routing *labels* don't exist anywhere yet (action-translation#251),
so the verdict block is deliberately the only source here.
"""

import datetime as dt
import json
import pathlib
import re
import statistics
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "verdicts.jsonl"
ORG = "QuantEcon"

_events_by_repo = None


def sh(*cmd, check=True):
    res = subprocess.run(cmd, check=check, capture_output=True, text=True)
    return res.stdout


def _load_events():
    """Current (non-superseded, parsed) verdict per PR, grouped by repo."""
    global _events_by_repo
    if _events_by_repo is not None:
        return _events_by_repo
    per_pr = {}
    if STORE.exists():
        for line in STORE.read_text().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("parse") != "ok" or ev.get("superseded"):
                continue
            key = (ev["repo"], ev["pr"])
            prev = per_pr.get(key)
            if prev is None or ev.get("commentUpdatedAt", "") >= prev.get("commentUpdatedAt", ""):
                per_pr[key] = ev
    _events_by_repo = {}
    for (repo, _pr), ev in per_pr.items():
        _events_by_repo.setdefault(repo, []).append(ev)
    return _events_by_repo


def _open_prs(repo):
    out = sh("gh", "pr", "list", "-R", f"{ORG}/{repo}", "--state", "open",
             "--limit", "200", "--json", "number,createdAt,files", check=False)
    try:
        return {p["number"]: p for p in json.loads(out)}
    except (json.JSONDecodeError, TypeError):
        return {}


def _primary_editor(work_dest):
    """First editor from .translate/config.yml `editors:` — schema-tolerant.

    Accepts either a `primary:` key or the first list item under
    `editors:`. Returns None when the block is absent (the pre-rollout
    state fleet-wide) or unparseable — fail-closed, like everything else.
    """
    cfg = pathlib.Path(work_dest) / ".translate" / "config.yml"
    if not cfg.exists():
        return None
    in_block = False
    for line in cfg.read_text().splitlines():
        if re.match(r"^editors\s*:", line):
            in_block = True
            continue
        if in_block:
            if line.strip() and not line.startswith((" ", "\t")):
                break  # block ended
            m = re.match(r"\s+primary\s*:\s*[\"']?@?([\w-]+)", line)
            if m:
                return m.group(1)
            m = re.match(r"\s*-\s*[\"']?@?([\w-]+)", line)
            if m:
                return m.group(1)
    return None


def _age_days(iso):
    created = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return max(0, (dt.datetime.now(dt.timezone.utc) - created).days)


def compute(target_repo, work_dest):
    """Per-edition review-lane block for latest.json."""
    current = _load_events().get(target_repo, [])
    if not current:
        return {"mode": "off", "verdicts": 0, "open_editor": {"count": 0},
                "auto_merge_recommended": {"d7": 0, "d30": 0},
                "share": {"auto_merge": 0, "editor": 0},
                "would_auto_merge": {"n": 0, "agree": 0},
                "primary_editor": _primary_editor(work_dest),
                "in_review_slugs": []}

    rec = lambda ev: (ev["verdict"].get("recommendation") or "").replace("_", "-")
    now = dt.datetime.now(dt.timezone.utc)

    # Mode: what the most recent verdict observed. `off` until the shadow
    # window opened; `active`/`tripped` pass through when the engine ships
    # them. Absence of the field reads as off, stated rather than guessed.
    latest = max(current, key=lambda ev: ev.get("commentCreatedAt", ""))
    mode = latest["verdict"].get("autoMergeMode") or "off"

    share = {"auto_merge": sum(1 for ev in current if rec(ev) == "auto-merge"),
             "editor": sum(1 for ev in current if rec(ev) == "editor")}

    def in_window(ev, days):
        ts = ev.get("commentCreatedAt")
        if not ts:
            return False
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (now - t).days < days

    auto_counts = {"d7": sum(1 for ev in current if rec(ev) == "auto-merge" and in_window(ev, 7)),
                   "d30": sum(1 for ev in current if rec(ev) == "auto-merge" and in_window(ev, 30))}

    wam = [ev for ev in current if ev["verdict"].get("wouldAutoMerge") is not None]
    would = {"n": len(wam),
             "agree": sum(1 for ev in wam
                          if ev["verdict"]["wouldAutoMerge"] == (rec(ev) == "auto-merge"))}

    open_prs = _open_prs(target_repo)
    editor_open = [ev for ev in current if rec(ev) == "editor" and ev["pr"] in open_prs]
    ages = sorted(_age_days(open_prs[ev["pr"]]["createdAt"]) for ev in editor_open)
    open_editor = {"count": len(editor_open)}
    if ages:
        open_editor["median_age_days"] = round(statistics.median(ages))
        open_editor["oldest_age_days"] = ages[-1]

    slugs = set()
    for ev in editor_open:
        for f in open_prs[ev["pr"]].get("files") or []:
            p = pathlib.PurePosixPath(f["path"])
            if len(p.parts) == 2 and p.parts[0] == "lectures" and p.suffix == ".md":
                slugs.add(p.stem)

    return {"mode": mode, "verdicts": len(current), "open_editor": open_editor,
            "auto_merge_recommended": auto_counts, "share": share,
            "would_auto_merge": would,
            "primary_editor": _primary_editor(work_dest),
            "in_review_slugs": sorted(slugs)}
