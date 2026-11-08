"""Turn a run's JSON files into metrics.json and the review page (review.py)."""
import json
import sys
from pathlib import Path

from .metrics import audit, beliefs, divergence, judge_changes, learned, llm_stats, remarks_reach, stale_cards, week_metrics
from .personas import BY_ID, register


def collect(out_dir: Path):
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    run["name"] = out_dir.name
    for spec in run.get("fresh") or []:
        register(spec)
    results, metrics, errors, people = {}, {}, {}, {}
    for pid in run["personas"]:
        path = out_dir / f"{pid}.json"
        if not path.exists():
            error = out_dir / f"{pid}.error.txt"
            errors[pid] = error.read_text()[-3000:] if error.exists() else "결과 파일 없음"
            continue
        p = BY_ID[pid]
        results[pid] = result = json.loads(path.read_text())
        judged = judge_changes(p, result)
        metrics[pid] = [week_metrics(p, w, judged.get(w["week"], [])) for w in result["weeks"]]
        people[pid] = {"beliefs": beliefs(p, result), "learned": learned(p, result), "staleCards": stale_cards(result),
                       "audit": audit(p, result, out_dir / f"{pid}.sqlite3")}
    summary = {
        "run": run, "errors": errors, "metrics": metrics, "people": people,
        "divergence": divergence(metrics),
        "remarks": {pid: remarks_reach(r) for pid, r in results.items()},
        "llm": {pid: llm_stats(r) for pid, r in results.items()},
    }
    return results, summary


def build(out_dir):
    out_dir = Path(out_dir)
    results, summary = collect(out_dir)
    (out_dir / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    from .review import render
    compare_path = out_dir / "compare.json"
    compare = json.loads(compare_path.read_text()) if compare_path.exists() else None
    page = out_dir / "report.html"
    page.write_text(render(results, summary, compare))
    return page


if __name__ == "__main__":
    print(build(sys.argv[1]))
