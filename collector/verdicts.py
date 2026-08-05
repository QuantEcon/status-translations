#!/usr/bin/env python3
"""Verdict capture (v1) — status-translations#1, WS8 of the human-review plan.

Captures `translation-review-verdict` blocks from review comments on
translation PRs across the production editions into data/verdicts.jsonl —
an append-only event store, separate from the data/history/ snapshots,
because verdicts are events (a population that includes merged and closed
PRs, where re-review supersedes in place) rather than current state.

Contract (docs/user/metadata-contract.md in action-translation), applied
fail-closed throughout:

- parse the LAST block in a comment, never the first (forgery defence);
- a comment that carries the review marker but no parseable last block is
  recorded as `parse: "no-verdict"`, never defaulted;
- the full verdict object is stored verbatim (scores are quantised, so
  profiles — not `overall` — are the signal; the severity×category
  distribution is computable from `findings[]`).

Re-review edits the comment in place (the engine calls updateComment), but
GitHub retains superseded bodies: for any comment with updated_at !=
created_at the collector walks GraphQL userContentEdits and records each
recoverable prior verdict with `superseded: true`. Events are keyed
(repo, pr, reviewedHeadSha, timestamp) — reruns and overlapping windows
are idempotent.

Routing fields are keyed on `recommendation`, which exists on every
verdict; `wouldAutoMerge` is shadow-only (null under `off`, i.e. on most
of the corpus) and is stored as confirmation, not as the routing signal.

Usage: verdicts.py [--since YYYY-MM-DD]   (default: 14 days back; the
nightly window overlaps deliberately — dedupe absorbs it. Backfill with
--since 2026-07-20, just before verdict v2 shipped in v0.22.0.)

Requires: gh (authenticated — GH_TOKEN in CI), python3.9+.
"""

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "verdicts.jsonl"
ORG = "QuantEcon"

VERDICT_BLOCK = re.compile(r"<!-- translation-review-verdict\s*(\{.*?\})\s*-->", re.S)
REVIEW_MARKER = "<!-- action-translation-review -->"
VERDICT_MARKER = "<!-- translation-review-verdict"

EDITS_QUERY = """query($id:ID!){ node(id:$id) { ... on IssueComment {
  userContentEdits(first:50){ totalCount nodes { editedAt diff } } } } }"""


def sh(*cmd, check=True):
    res = subprocess.run(cmd, check=check, capture_output=True, text=True)
    return res.stdout


def concat_json(text):
    """Parse `gh api --paginate` output: one or more JSON arrays back to back."""
    dec, idx, out = json.JSONDecoder(), 0, []
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, idx = dec.raw_decode(text, idx)
        out.extend(obj if isinstance(obj, list) else [obj])
    return out


def parse_last_block(body):
    """(verdict, parse-state). Last block only; malformed last block is
    no-verdict — never fall back to an earlier block, that is how a
    forgery wins."""
    blocks = VERDICT_BLOCK.findall(body or "")
    if not blocks:
        return None, "no-verdict"
    try:
        v = json.loads(blocks[-1])
        if not isinstance(v, dict):
            return None, "no-verdict"
        return v, "ok"
    except json.JSONDecodeError:
        return None, "no-verdict"


def event_key(ev):
    v = ev.get("verdict") or {}
    if ev["parse"] == "ok":
        return ("v", ev["repo"], ev["pr"], v.get("reviewedHeadSha"), v.get("timestamp"))
    return ("nv", ev["repo"], ev["pr"], ev["commentId"], ev["commentUpdatedAt"])


def comment_edits(node_id):
    out = sh("gh", "api", "graphql", "-f", f"query={EDITS_QUERY}", "-f", f"id={node_id}",
             check=False)
    try:
        edits = json.loads(out)["data"]["node"]["userContentEdits"]
        if edits["totalCount"] > 50:
            print(f"  warn: {edits['totalCount']} edits on comment {node_id}, walked 50")
        return [n for n in edits["nodes"] if n.get("diff")]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def capture_pr(repo, pr, today):
    events = []
    comments = concat_json(sh(
        "gh", "api", f"repos/{ORG}/{repo}/issues/{pr['number']}/comments?per_page=100",
        "--paginate", check=False))
    for c in comments:
        body = c.get("body") or ""
        if REVIEW_MARKER not in body and VERDICT_MARKER not in body:
            continue
        verdict, parse = parse_last_block(body)
        base = {
            "schemaVersion": 1, "capturedAt": today,
            "repo": repo, "pr": pr["number"], "prState": pr["state"],
            "commentId": c["id"], "commentCreatedAt": c["created_at"],
            "commentUpdatedAt": c["updated_at"],
        }
        events.append({**base, "superseded": False, "parse": parse, "verdict": verdict})
        # Superseded verdicts survive in GitHub's edit history; recover them.
        if c["updated_at"] != c["created_at"]:
            for edit in comment_edits(c["node_id"]):
                ev_verdict, ev_parse = parse_last_block(edit["diff"])
                if ev_parse != "ok":
                    continue  # pre-verdict bodies and prose edits, not failures
                events.append({**base, "commentUpdatedAt": edit["editedAt"],
                               "superseded": True, "parse": "ok", "verdict": ev_verdict})
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None,
                    help="capture PRs updated since this date (default: 14 days back)")
    args = ap.parse_args()
    since = args.since or (dt.date.today() - dt.timedelta(days=14)).isoformat()
    today = dt.date.today().isoformat()

    config = json.loads((ROOT / "collector" / "config.json").read_text())
    repos = [e["target_repo"] for s in config["sources"] if not s.get("phase")
             for e in s["editions"] if e.get("target_repo")]

    seen = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                seen.add(event_key(json.loads(line)))

    fresh = []
    for repo in repos:
        prs = json.loads(sh(
            "gh", "pr", "list", "-R", f"{ORG}/{repo}", "--state", "all",
            "--limit", "300", "--search", f"updated:>={since}",
            "--json", "number,state", check=False) or "[]")
        n_before = len(fresh)
        for pr in prs:
            for ev in capture_pr(repo, pr, today):
                key = event_key(ev)
                if key not in seen:
                    seen.add(key)
                    fresh.append(ev)
        print(f"{repo}: {len(prs)} PRs updated since {since}, "
              f"{len(fresh) - n_before} new events")

    fresh.sort(key=lambda e: (e["repo"], e["pr"],
                              (e.get("verdict") or {}).get("timestamp") or e["commentUpdatedAt"]))
    with OUT.open("a") as f:
        for ev in fresh:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    print(f"appended {len(fresh)} events to data/verdicts.jsonl")


if __name__ == "__main__":
    main()
