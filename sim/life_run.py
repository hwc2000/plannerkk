"""Run the daily-life cases (several projects at once) and write the report.

    .venv/bin/python -m sim.life_run --weeks 4                 # every case and person
    .venv/bin/python -m sim.life_run --only study_gym,job_study.cap
    .venv/bin/python -m sim.life_run --fake --weeks 1          # no AI calls: wiring only

Output: sim/out/<run>/ with one JSON + SQLite per "case.person", life.json and report.html.
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


def _play(uid, weeks, out_dir, fake):
    sys.path.insert(0, str(ROOT))
    from sim import life_play
    try:
        if fake:
            from sim.run import FakeLLM
            life_play.ExecutionLLM = FakeLLM
            os.environ.setdefault("OPENAI_API_KEY", "fake")
        life_play.run_life(uid, weeks, Path(out_dir))
    except Exception:
        (Path(out_dir) / f"{uid}.error.txt").write_text(traceback.format_exc())
        raise


def main(argv=None):
    from dotenv import load_dotenv
    from sim.life import players
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--only", default="")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--template", action="store_true", help="fixed sentences instead of AI-written check-ins")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    os.environ["SIM_SEED"] = str(args.seed)
    os.environ["SIM_WRITER"] = "0" if (args.template or args.fake) else "1"
    ids = players(args.only)
    run = args.out or "life-" + datetime.now().strftime("%m%d-%H%M") + ("-fake" if args.fake else "")
    out_dir = ROOT / "sim" / "out" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    model = "fake" if args.fake else os.getenv("OPENAI_PLAN_MODEL", "gpt-4o-mini")
    (out_dir / "run.json").write_text(json.dumps({
        "kind": "life", "weeks": args.weeks, "players": ids, "model": model, "seed": args.seed,
        "writer": "template" if os.environ["SIM_WRITER"] == "0" else (os.getenv("SIM_WRITER_MODEL") or os.getenv("OPENAI_PLAN_MODEL") or "gpt-6.1-terra"),
        "started": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False))
    print(f"run {run}: {len(ids)} players x {args.weeks} weeks, model {model}", flush=True)
    context = multiprocessing.get_context("spawn")
    workers = [context.Process(target=_play, args=(uid, args.weeks, str(out_dir), args.fake), name=uid) for uid in ids]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
        print(f"  {worker.name}: {'ok' if worker.exitcode == 0 else 'FAILED'}", flush=True)
    from sim.life_report import build
    print(f"report: {build(out_dir)}", flush=True)


if __name__ == "__main__":
    main()
