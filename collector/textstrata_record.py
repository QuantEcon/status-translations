"""Record a textstrata scan into the data store (QuantEcon/textstrata#7).

Reads the per-edition scan outputs from work/out/<config>/ and writes the
run-level artefacts into data/textstrata/ — a dated history entry plus a
latest/ copy for the site. Only the small, trendable artefacts are kept:
run.json (no per-person data by construction) and documents.json with its
human_ids removed (project-management fields, not for publication). The heavy
artefacts (pairs.jsonl, commits.jsonl, overwrites.json) regenerate
deterministically from the HEAD sha each run.json records, so committing
them would buy repo bloat and nothing else.
"""
import json
import pathlib
import shutil
from datetime import UTC, datetime

EDITIONS = ("intro-zh-cn", "python-zh-cn", "programming-zh-cn")


def main() -> None:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    hist = pathlib.Path("data/textstrata/history") / day
    latest = pathlib.Path("data/textstrata/latest")
    hist.mkdir(parents=True, exist_ok=True)
    latest.mkdir(parents=True, exist_ok=True)
    for cfg in EDITIONS:
        out = pathlib.Path("work/out") / cfg
        docs = json.loads((out / "documents.json").read_text(encoding="utf-8"))
        for rec in docs.values():
            rec.pop("human_ids", None)
        redacted = json.dumps(docs, ensure_ascii=False, indent=1)
        for dest in (hist, latest):
            shutil.copy(out / "run.json", dest / f"{cfg}.run.json")
            (dest / f"{cfg}.documents.json").write_text(redacted, encoding="utf-8")
        head = json.loads((out / "run.json").read_text(encoding="utf-8"))["head"]
        print(f"{cfg}: recorded @ {head[:7]}")


if __name__ == "__main__":
    main()
