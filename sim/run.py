"""Run the check-in experiment and write the report.

    .venv/bin/python -m sim.run                    # every user, 3 weeks, the model in .env
    .venv/bin/python -m sim.run --weeks 2 --only steady,short_focus
    .venv/bin/python -m sim.run --fake --weeks 1   # no AI calls: checks the wiring only
    .venv/bin/python -m sim.run --seed 2 --fresh 10 # another draw: new random users, new days, new words

Needs one extra package for the fake clock: .venv/bin/python -m pip install time-machine
Each user plays in a process of its own (the fake clock is per process).
Output: sim/out/<run>/ with one JSON per user, metrics.json and report.html.
"""
import argparse
import json
import multiprocessing
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeLLM:
    """Wiring check only: fills the week with tasks of the cap, extracts nothing from words."""

    async def generate(self, **kwargs):
        if kwargs["name"].startswith("planner_"):
            return {}
        context = kwargs["context"]
        project = (context.get("projects") or [{}])[0]
        block = project.get("maxBlockMinutes") or 60
        count = max(1, min(40, (context.get("budgetMinutes") or 1200) // block))
        return {"tasks": [{"title": f"정처기 실기 공부 {i + 1}", "minutes": block, "doneWhen": "정리한 내용 저장",
                           "dueDate": None, "projectId": project.get("id")} for i in range(count)]}


def _play(persona_id, weeks, out_dir, fake, spec=None):
    sys.path.insert(0, str(ROOT))
    from sim import driver
    from sim.personas import BY_ID, register
    if spec:
        register(spec)
    try:
        if fake:
            driver.ExecutionLLM = FakeLLM
            os.environ.setdefault("OPENAI_API_KEY", "fake")
        driver.run_persona(BY_ID[persona_id], weeks, Path(out_dir))
    except Exception:
        (Path(out_dir) / f"{persona_id}.error.txt").write_text(traceback.format_exc())
        raise


def main(argv=None):
    from dotenv import load_dotenv
    from dataclasses import asdict
    from sim.personas import PERSONAS, make_fresh
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=3)
    parser.add_argument("--only", default="")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--seed", type=int, default=1, help="draws the days, the words and the fresh users")
    parser.add_argument("--fresh", type=int, default=10, help="random users drawn for this run (never used to design rules)")
    parser.add_argument("--template", action="store_true", help="fixed sentences instead of AI-written check-ins")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    os.environ["SIM_SEED"] = str(args.seed)
    os.environ["SIM_WRITER"] = "0" if (args.template or args.fake) else "1"
    fresh = make_fresh(args.fresh, args.seed)
    specs = {p.id: asdict(p) for p in fresh}
    ids = [p.id for p in [*PERSONAS, *fresh] if not args.only or p.id in args.only.split(",")]
    run = args.out or datetime.now().strftime("%m%d-%H%M") + ("-fake" if args.fake else "")
    out_dir = ROOT / "sim" / "out" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    model = "fake" if args.fake else os.getenv("OPENAI_PLAN_MODEL", "gpt-4o-mini")
    (out_dir / "run.json").write_text(json.dumps({
        "weeks": args.weeks, "personas": ids, "model": model, "seed": args.seed,
        "writer": "template" if os.environ["SIM_WRITER"] == "0" else (os.getenv("SIM_WRITER_MODEL") or os.getenv("OPENAI_PLAN_MODEL") or "gpt-6.1-terra"),
        "fresh": [specs[i] for i in ids if i in specs],
        "started": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False))
    print(f"run {run}: {len(ids)} users x {args.weeks} weeks, model {model}", flush=True)
    context = multiprocessing.get_context("spawn")
    workers = [context.Process(target=_play, args=(pid, args.weeks, str(out_dir), args.fake, specs.get(pid)), name=pid)
               for pid in ids]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
        print(f"  {worker.name}: {'ok' if worker.exitcode == 0 else 'FAILED'}", flush=True)
    from sim.report import build
    report = build(out_dir)
    print(f"report: {report}", flush=True)


if __name__ == "__main__":
    main()
