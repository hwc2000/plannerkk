"""Project profiles: per-project settings on top of the user profile.

The adaptive benefit under test: what one project teaches (or what the user
sets for it) changes that project's plans only, while every project keeps
inheriting the user profile for the rest.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.execution_learning import propose_update
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS, FakeLLM

PROJECT_A = {"id": "project-a", "title": "토익", "goal": "800점", "startDate": "2030-01-01", "dueDate": "2030-03-31"}
PROJECT_B = {"id": "project-b", "title": "졸업작품", "goal": "시연", "startDate": "2030-01-01", "dueDate": "2030-03-31"}
BASE_BLOCK = 30  # PLAIN_ANSWERS' focus block


class ProjectProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=self.llm))
        self.revision = self.state()["revision"]

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def state(self):
        return self.client.get("/api/execution").json()

    def call(self, path, status=200, method="post", **body):
        response = getattr(self.client, method)(path, json={"revision": self.revision, **body})
        self.assertEqual(response.status_code, status, response.text)
        data = response.json()
        if status == 200 and "revision" in data:
            self.revision = data["revision"]
        return data

    def setup_profile(self):
        self.call("/api/execution/profile", answers=PLAIN_ANSWERS)
        self.call("/api/execution/profile/confirm")
        settings = {"slots": [{"day": 0, "hour": 18}, {"day": 0, "hour": 19}], "view": "timeline"}
        self.call("/api/execution/settings", method="put", settings=settings)

    def plan_for(self, project):
        self.call("/api/execution/plan", goal=project["goal"], startDate="2030-01-07", consent=True, project=project)
        return self.call("/api/execution/plan/confirm", planId=self.state()["planDraft"]["id"], project=project)["plan"]

    def context_for(self, project):
        return self.call("/api/execution/planning-context", goal="계획", startDate="2030-01-07", project=project)

    def fail_three_long_tasks(self, project_id):
        """Three 50-minute tasks of one project left unfinished for lack of time."""
        def add(doc):
            plan, profile = doc["plan"], doc["profile"]
            project_profile = doc["projectProfiles"].get(project_id) or {}
            for i in range(3):
                doc["executionRecords"].append({
                    "id": f"{project_id}-record-{i}", "planId": plan["id"], "taskId": f"task-{i}",
                    "profileId": profile["id"], "profileVersion": profile["version"], "projectId": project_id,
                    "projectProfileId": project_profile.get("id"), "taskTitle": "긴 작업", "plannedMinutes": 50,
                    "actualMinutes": 20, "remainingMinutes": 30, "result": "partial", "reasonCode": "time_shortage",
                    "note": "", "difficulty": None, "recoveryAction": None,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                })
            propose_update(doc, None)  # records of a project never make a user-profile change
            propose_update(doc, project_id)
        self.revision = self.store.change(self.revision, add)["revision"]
        [proposal] = self.state()["profileUpdateProposals"]
        return proposal

    def test_values_set_for_a_project_apply_to_that_project_only(self):
        self.setup_profile()
        profile = self.state()["profile"]

        data = self.call("/api/execution/projects/project-a/profile", method="put", overrides={"blockMinutes": 15})

        project_profile = data["projectProfiles"]["project-a"]
        self.assertEqual(project_profile["version"], 1)
        self.assertEqual(project_profile["overrides"],
                         {"blockMinutes": {"value": 15, "source": "declared", "proposalId": None}})
        self.assertEqual((data["profile"]["id"], data["profile"]["version"]), (profile["id"], profile["version"]))
        context_a, context_b = self.context_for(PROJECT_A), self.context_for(PROJECT_B)
        self.assertEqual(context_a["userProfile"]["planningPreferences"]["blockMinutes"], 15)
        self.assertEqual(context_a["userProfile"]["projectOverrides"]["blockMinutes"]["baseValue"], BASE_BLOCK)
        self.assertEqual(context_a["projectProfile"]["id"], project_profile["id"])
        self.assertEqual(context_b["userProfile"]["planningPreferences"]["blockMinutes"], BASE_BLOCK)
        self.assertIsNone(context_b["projectProfile"])

        self.llm.plan_minutes = 15
        draft = self.call("/api/execution/plan", goal="단어", startDate="2030-01-07", consent=True,
                          project=PROJECT_A)["planDraft"]

        self.assertEqual(self.llm.plan_calls[-1]["context"]["maxBlockMinutes"], 15)
        self.assertEqual(draft["projectProfileId"], project_profile["id"])
        reason = next(r for r in draft["personalization"] if r["key"] == "taskLength")
        self.assertEqual(reason["source"], "project")
        self.assertIn(f"기본 프로필 값은 {BASE_BLOCK}분", reason["because"])

    def test_recovery_route_follows_each_projects_own_preference(self):
        self.setup_profile()
        self.call("/api/execution/projects/project-a/profile", method="put", overrides={"recoveryPreference": "replan"})
        tired = {"completed": False, "actualMinutes": 5, "reasonCode": "fatigue"}

        task_a = next(e for e in self.plan_for(PROJECT_A)["entries"] if e["kind"] == "task")
        moved = self.call("/api/adaptive/check-in", taskId=task_a["id"], consent=True, checkIn=tired)
        task_b = next(e for e in self.plan_for(PROJECT_B)["entries"] if e["kind"] == "task")
        shrunk = self.call("/api/adaptive/check-in", taskId=task_b["id"], consent=True, checkIn=tired)

        # Same reason, different projects: A moves the work (its preference), B shrinks it (the default).
        self.assertEqual(moved["recoveryDraft"]["strategy"], "reschedule")
        self.assertEqual(shrunk["recoveryDraft"]["strategy"], "shrink")
        self.assertEqual(len(self.llm.shrink_calls), 1)

    def test_project_values_that_do_not_fit_the_user_profile_are_rejected(self):
        self.setup_profile()
        for overrides, message in (
            ({"starterMinutes": 40}, "시작 작업은 집중 구간을 넘을 수 없습니다"),
            ({"blockMinutes": "15"}, "집중 구간"),
            ({"blockMinutes": True}, "집중 구간"),
            ({"scheduleStyle": "time_blocks"}, "바꿀 수 없는 항목 scheduleStyle"),
        ):
            data = self.call("/api/execution/projects/project-a/profile", 400, method="put", overrides=overrides)
            self.assertIn(message, data["detail"])
        self.assertEqual(self.state()["projectProfiles"], {})

    def test_failures_in_one_project_shrink_that_project_only(self):
        self.setup_profile()
        profile = self.state()["profile"]
        plan = self.plan_for(PROJECT_A)
        self.assertIsNone(plan["projectProfileId"])

        proposal = self.fail_three_long_tasks("project-a")

        self.assertEqual((proposal["projectId"], proposal["projectProfileId"]), ("project-a", None))
        self.assertEqual(proposal["proposedChanges"], {"blockMinutes": {"from": BASE_BLOCK, "to": 20}})
        self.assertTrue(proposal["reason"].startswith("이 프로젝트에서"))

        data = self.call(f"/api/execution/proposals/{proposal['id']}/approve")

        # The user profile is untouched, so other projects' plans stay current.
        self.assertEqual((data["profile"]["id"], data["profile"]["version"]), (profile["id"], profile["version"]))
        project_profile = data["projectProfiles"]["project-a"]
        self.assertEqual(project_profile["overrides"]["blockMinutes"],
                         {"value": 20, "source": "learned", "proposalId": proposal["id"]})
        [pattern] = project_profile["learnedPatterns"]
        self.assertEqual((pattern["projectId"], pattern["approvedProposalId"]), ("project-a", proposal["id"]))
        approved = next(p for p in data["profileUpdateProposals"] if p["id"] == proposal["id"])
        self.assertEqual(approved["appliedProjectProfileId"], project_profile["id"])
        self.assertEqual(self.context_for(PROJECT_A)["userProfile"]["planningPreferences"]["blockMinutes"], 20)
        self.assertEqual(self.context_for(PROJECT_B)["userProfile"]["planningPreferences"]["blockMinutes"], BASE_BLOCK)

        # The plan made with the old project settings is replanned, not patched.
        task = next(e for e in plan["entries"] if e["kind"] == "task")
        stale = self.call("/api/adaptive/check-in", 400, taskId=task["id"], consent=True,
                          checkIn={"completed": False, "actualMinutes": 5, "reasonCode": "task_too_large"})
        self.assertIn("‘토익’ 설정이 바뀌었습니다", stale["detail"])
        self.llm.plan_minutes = 20
        draft = self.call("/api/execution/plan", goal=plan["goal"], startDate=plan["startDate"], consent=True,
                          project=PROJECT_A, profileChangeProposalId=proposal["id"])["planDraft"]

        context = self.llm.plan_calls[-1]["context"]
        self.assertEqual(context["maxBlockMinutes"], 20)
        self.assertEqual((context["profileChange"]["scope"], context["profileChange"]["projectId"]), ("project", "project-a"))
        self.assertEqual(draft["projectProfileId"], project_profile["id"])
        reason = next(r for r in draft["personalization"] if r["key"] == "taskLength")
        self.assertEqual(reason["source"], "learned")
        self.assertIn(f"이 프로젝트의 실행 기록 3건을 근거로 승인한 변경({BASE_BLOCK}분 → 20분)", reason["because"])
        confirmed = self.call("/api/execution/plan/confirm", planId=draft["id"], project=PROJECT_A)["plan"]
        self.assertEqual(confirmed["projectProfileId"], project_profile["id"])

    def test_a_project_change_never_replans_another_projects_plan(self):
        self.setup_profile()
        plan_b = self.plan_for(PROJECT_B)
        proposal = self.fail_three_long_tasks("project-a")
        self.call("/api/execution/plan", goal="졸업작품 시연", startDate="2030-01-07", consent=True, project=PROJECT_B)
        draft_b = self.state()["planDraft"]

        self.call(f"/api/execution/proposals/{proposal['id']}/approve")

        self.assertEqual(self.state()["planDraft"], draft_b)  # project B's draft is still valid
        data = self.call("/api/execution/plan", 400, goal=plan_b["goal"], startDate=plan_b["startDate"], consent=True,
                         project=PROJECT_B, profileChangeProposalId=proposal["id"])
        self.assertIn("지금 계획에 없는 프로젝트", data["detail"])
        self.assertEqual(self.state()["plan"], plan_b)
        task = next(e for e in plan_b["entries"] if e["kind"] == "task")
        recovery = self.call("/api/adaptive/check-in", taskId=task["id"], consent=True,
                             checkIn={"completed": False, "actualMinutes": 5, "reasonCode": "task_too_large"})
        self.assertEqual(recovery["result"]["approvalStatus"], "waiting")

    def test_a_value_the_user_sets_replaces_the_learned_one(self):
        self.setup_profile()
        self.plan_for(PROJECT_A)
        proposal = self.fail_three_long_tasks("project-a")
        self.call(f"/api/execution/proposals/{proposal['id']}/approve")

        data = self.call("/api/execution/projects/project-a/profile", method="put", overrides={"blockMinutes": 25})

        project_profile = data["projectProfiles"]["project-a"]
        self.assertEqual(project_profile["version"], 2)
        self.assertEqual(project_profile["overrides"]["blockMinutes"],
                         {"value": 25, "source": "declared", "proposalId": None})
        self.assertEqual([p["status"] for p in project_profile["learnedPatterns"]], ["superseded"])
        self.assertEqual([r["source"] for r in data["projectProfileRevisions"]], ["proposal_approved", "declared"])


if __name__ == "__main__":
    unittest.main()
