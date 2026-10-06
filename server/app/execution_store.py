"""SQLite storage for one local user's execution profile and plans."""
import json
import os
import sqlite3
from .user_profile import normalize_profile_state
from contextlib import closing
from pathlib import Path


class ConflictError(ValueError):
    pass


def empty_state():
    return {"revision": 0, "profile": None, "profileDraft": None,
            "settings": {"slots": [], "view": "timeline"}, "plan": None, "planDraft": None,
            "recoveryDrafts": {}, "executionRecords": [], "profileUpdateProposals": [],
            "surveyResponses": [], "profileRevisions": [], "memories": [], "profileConversations": []}


class ExecutionStore:
    def __init__(self, path=None, *, user_id="local"):
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("사용자 식별자가 필요합니다.")
        self.user_id = user_id
        self.path = Path(path or os.getenv("REPLAN_DB_PATH") or Path(__file__).resolve().parents[2] / "data" / "replan.sqlite3")

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("CREATE TABLE IF NOT EXISTS execution_state (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS user_execution_state (user_id TEXT PRIMARY KEY, document TEXT NOT NULL)")
        db.commit()
        return db

    def read(self):
        with closing(self.connect()) as db:
            row = self._row(db)
            return self._decode(row)

    def change(self, revision, mutation):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db)
            state = self._decode(row)
            if state["revision"] != revision:
                raise ConflictError("다른 화면에서 데이터가 변경되었습니다. 새로 불러온 내용을 확인하고 다시 시도해 주세요.")
            mutation(state)
            state["revision"] = revision + 1
            if self.user_id == "local":
                db.execute("INSERT INTO execution_state VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                           (json.dumps(state, ensure_ascii=False),))
            else:
                db.execute("INSERT INTO user_execution_state VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET document=excluded.document",
                           (self.user_id, json.dumps(state, ensure_ascii=False)))
            return state

    def _row(self, db):
        if self.user_id == "local":
            return db.execute("SELECT document FROM execution_state WHERE id=1").fetchone()
        return db.execute("SELECT document FROM user_execution_state WHERE user_id=?", (self.user_id,)).fetchone()

    def _decode(self, row):
        state = {**empty_state(), **json.loads(row[0])} if row else empty_state()
        return normalize_profile_state(state, self.user_id)
