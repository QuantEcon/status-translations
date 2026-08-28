"""Record a textstrata scan into the data store (QuantEcon/textstrata#7).

Reads the per-edition scan outputs from work/out/<config>/ and writes the
run-level artefacts into data/textstrata/ — a history entry dated by the
scan itself plus a latest/ copy for the site. Only the small, trendable
artefacts are kept, and both are rewritten before they touch this public
repo: run.json loses its `repo` field (a scan-machine filesystem path;
`config` and `head` already identify the run) and documents.json loses its
`human_ids` (project-management fields, not for publication). The heavy
artefacts (pairs.jsonl, commits.jsonl, overwrites.json) regenerate
deterministically from the HEAD sha each run.json records, so committing
them would buy repo bloat and nothing else.
"""
import json
import pathlib

EDITIONS = ("intro-zh-cn", "python-zh-cn", "programming-zh-cn")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    runs = {}
    for cfg in EDITIONS:
        run = json.loads((pathlib.Path("work/out") / cfg / "run.json").read_text(encoding="utf-8"))
        run.pop("repo", None)
        runs[cfg] = run
    # date the history entry by the scan, not the recording clock: a run that
    # crosses UTC midnight files under the day it started
    day = min(run["scanned_at"] for run in runs.values())[:10]
    hist = pathlib.Path("data/textstrata/history") / day
    latest = pathlib.Path("data/textstrata/latest")
    hist.mkdir(parents=True, exist_ok=True)
    latest.mkdir(parents=True, exist_ok=True)
    for cfg in EDITIONS:
        docs = json.loads((pathlib.Path("work/out") / cfg / "documents.json").read_text(encoding="utf-8"))
        for rec in docs.values():
            rec.pop("human_ids", None)
        for dest in (hist, latest):
            (dest / f"{cfg}.run.json").write_text(_dump(runs[cfg]), encoding="utf-8")
            (dest / f"{cfg}.documents.json").write_text(_dump(docs), encoding="utf-8")
        print(f"{cfg}: recorded @ {runs[cfg]['head'][:7]} under {day}")


if __name__ == "__main__":
    main()
