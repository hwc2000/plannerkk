"""The check-in experiment (sim/) must not leak into the app.

Virtual users exist to test the app, not to shape it: the app never imports the
experiment or names its users, and the experiment reaches the app only through
the same HTTP API the screens use.
"""
import re
import unittest
from pathlib import Path

from sim.life import PEOPLE, SCENARIOS
from sim.personas import PERSONAS, PROJECT

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "server" / "app"
SIM = ROOT / "sim"
SIM_MAY_USE = {"server.app.main", "server.app.execution_store", "server.app.execution_llm"}


def sources(folder):
    return {path: path.read_text(encoding="utf-8") for path in folder.rglob("*.py")}


class SimSeparationTests(unittest.TestCase):
    def test_the_app_never_imports_the_experiment(self):
        for path, text in sources(APP).items():
            self.assertIsNone(re.search(r"^\s*(from|import)\s+sim\b", text, re.M), path)

    def test_the_app_never_names_a_virtual_user(self):
        marks = [PROJECT["id"], PROJECT["title"], *(p.label for p in PERSONAS), *(r for p in PERSONAS for r in p.remarks)]
        # Daily-life cases (life.py): project ids and goals, people and what they say.
        marks += [x for s in SCENARIOS for p in s.projects for x in (p.id, p.goal)]
        marks += [*(p.label for p in PEOPLE), *(r for p in PEOPLE for r in p.remarks)]
        for path, text in sources(APP).items():
            for mark in marks:
                self.assertNotIn(mark, text, f"{path} names the experiment: {mark}")

    def test_the_experiment_uses_the_app_only_through_its_api(self):
        for path, text in sources(SIM).items():
            used = set(re.findall(r"^\s*from\s+(server\.app[\w.]*)\s+import", text, re.M))
            used |= set(re.findall(r"^\s*import\s+(server\.app[\w.]*)", text, re.M))
            self.assertLessEqual(used, SIM_MAY_USE, path)


if __name__ == "__main__":
    unittest.main()
