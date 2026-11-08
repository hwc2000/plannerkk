"""Before/after: the same users, days and seeds run on two versions of the app.

    .venv/bin/python -m sim.compare BEFORE_RUN AFTER_RUN [BEFORE_RUN2 AFTER_RUN2 ...]

Each pair shares a seed, so the users, their days and the random draws match; only
the app differs (the AI's own answers still vary from run to run, which is why
several seeds are compared).  Fixed users and fresh users are kept apart: fresh
users were never looked at while changing the app.
"""
import json
import sys
from pathlib import Path
from statistics import mean

from .report import collect
from .review import relevant, TRAITS
from .personas import BY_ID

LATE_WEEKS = (3, 4)   # after the app has had two weeks to learn


def repeats(result):
    """Per week from the second: share of the first plan's tasks that repeat a title already finished."""
    done, out = set(), []
    for week in result["weeks"]:
        plan = next((x for x in week["plans"] if x["tasks"]), None)
        if plan and week["week"] > 1:
            titles = [t["title"] for t in plan["tasks"]]
            out.append(sum(t in done for t in titles) / len(titles) if titles else 0)
        for day in week["days"]:
            done |= {o["title"] for o in day["outcomes"] if o["result"] == "completed"}
    return mean(out) if out else None


def person_scores(pid, result, metrics, person):
    late = [m for m in metrics if m["week"] in LATE_WEEKS and m.get("tests")]
    last = person["beliefs"][-1] if person["beliefs"] else {}
    keys = [k for k, _ in TRAITS if relevant(BY_ID[pid], k, last)]
    wrong = sum(1 for m in metrics for x in m.get("proposals", []) if x.get("verdict") == "wrong")
    stuck = sum(1 for m in metrics for x in m.get("proposals", [])
                if x.get("verdict") != "wrong" and x.get("worseAfterProbe") and (x.get("undoneAfter") is None or x["undoneAfter"] > 7))
    reads = [m["tests"]["extraction"]["value"] for m in metrics if m.get("tests") and m["tests"]["extraction"]["value"] is not None]
    return {
        "completion": mean(m["tests"]["completion"]["value"] for m in late) if late else None,
        "progress": mean(m["tests"]["progress"]["value"] for m in late) if late else None,
        "beliefs": sum(last[k]["state"] == "right" for k in keys) / len(keys) if keys else None,
        "badChanges": wrong + stuck,
        "repeats": repeats(result),
        "reading": mean(reads) if reads else None,
    }


def scores(run_dir):
    results, summary = collect(run_dir)
    return {pid: person_scores(pid, results[pid], summary["metrics"][pid], summary["people"][pid]) for pid in results}, summary["run"]


def compare(pairs):
    rows = {}
    for before_dir, after_dir in pairs:
        before, run_b = scores(before_dir)
        after, run_a = scores(after_dir)
        seed = run_a.get("seed")
        for pid in after:
            if pid not in before:
                continue
            key = pid if not pid.startswith("fresh") else f"{pid}@{seed}"
            rows[key] = {"pid": pid, "seed": seed, "fresh": pid.startswith("fresh"),
                         "label": BY_ID[pid].label + (f" (seed {seed})" if pid.startswith("fresh") else ""),
                         "before": before[pid], "after": after[pid]}
            if not pid.startswith("fresh"):
                rows[key].setdefault("seeds", []).append(seed)
    # Fixed users repeat across seeds: average them per user.
    merged = {}
    for key, row in rows.items():
        merged.setdefault(row["pid"] if not row["fresh"] else key, []).append(row)
    table = []
    for key, items in merged.items():
        avg = lambda side, metric: _mean([i[side][metric] for i in items])
        table.append({"key": key, "label": items[0]["label"], "fresh": items[0]["fresh"], "runs": len(items),
                      **{f"{side}.{metric}": avg(side, metric) for side in ("before", "after")
                         for metric in ("completion", "progress", "beliefs", "badChanges", "repeats", "reading")}})
    groups = {}
    for name, members in (("fixed", [r for r in table if not r["fresh"]]), ("fresh", [r for r in table if r["fresh"]])):
        groups[name] = {metric: {side: _mean([r[f"{side}.{metric}"] for r in members]) for side in ("before", "after")}
                        for metric in ("completion", "progress", "beliefs", "badChanges", "repeats", "reading")}
        groups[name]["better"] = sum(1 for r in members if (r["after.progress"] or 0) > (r["before.progress"] or 0) + 0.05)
        groups[name]["worse"] = sum(1 for r in members if (r["after.progress"] or 0) < (r["before.progress"] or 0) - 0.05)
        groups[name]["count"] = len(members)
    return {"pairs": [[str(a), str(b)] for a, b in pairs], "table": table, "groups": groups}


def _mean(values):
    values = [v for v in values if v is not None]
    return round(mean(values), 3) if values else None


if __name__ == "__main__":
    args = sys.argv[1:]
    pairs = list(zip(args[0::2], args[1::2]))
    out = compare(pairs)
    target = Path(pairs[-1][1]) / "compare.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out["groups"], ensure_ascii=False, indent=1))
