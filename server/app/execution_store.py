"""SQLite storage for one local user's execution profile and plans."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


class ConflictError(ValueError):
    pass


def empty_state():
    return {"revision": 0, "profile": None, "profileDraft": None,
            "settings": {"slots": [], "view": "timeline"}, "plan": None, "planDraft": None}


class ExecutionStore:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("REPLAN_DB_PATH") or Path(__file__).resolve().parents[2] / "data" / "replan.sqlite3")

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("CREATE TABLE IF NOT EXISTS execution_state (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL)")
        db.commit()
        return db

    def read(self):
        with closing(self.connect()) as db:
            row = db.execute("SELECT document FROM execution_state WHERE id=1").fetchone()
            return json.loads(row[0]) if row else empty_state()

    def change(self, revision, mutation):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM execution_state WHERE id=1").fetchone()
            state = json.loads(row[0]) if row else empty_state()
            if state["revision"] != revision:
                raise ConflictError("다른 화면에서 데이터가 변경되었습니다. 새로 불러온 내용을 확인하고 다시 시도해 주세요.")
            mutation(state)
            state["revision"] = revision + 1
            db.execute("INSERT INTO execution_state VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                       (json.dumps(state, ensure_ascii=False),))
            return state
