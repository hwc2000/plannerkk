"""Email/password sign-up and login with server-side sessions.

Users and sessions live in the same SQLite file as the execution state. Passwords
are hashed with PBKDF2-SHA256 (stdlib only), session tokens are random and only
their SHA-256 hash is stored. The browser keeps the token in an HttpOnly cookie.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .execution_store import ExecutionStore

SESSION_COOKIE = "replan_session"
SESSION_DAYS = 14
PBKDF2_ITERATIONS = 390_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60

current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def _now():
    return int(time.time())


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(candidate.hex(), digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthStore:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("REPLAN_DB_PATH") or Path(__file__).resolve().parents[2] / "data" / "replan.sqlite3")

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS user_workspace (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            document TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        db.commit()
        return db

    # users -----------------------------------------------------------------
    def create_user(self, email: str, password: str, display_name: str) -> dict:
        user = {"id": str(uuid4()), "email": email, "displayName": display_name,
                "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with closing(self.connect()) as db, db:
            try:
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                           (user["id"], email, display_name, hash_password(password), user["createdAt"]))
            except sqlite3.IntegrityError as exc:
                raise ValueError("이미 가입된 이메일입니다.") from exc
        return user

    def authenticate(self, email: str, password: str) -> dict | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT id, email, display_name, password_hash, created_at FROM users WHERE email=?",
                             (email,)).fetchone()
        if not row:
            hash_password(password)  # keep timing similar for unknown emails
            return None
        if not verify_password(password, row[3]):
            return None
        return {"id": row[0], "email": row[1], "displayName": row[2], "createdAt": row[4]}

    def get_user(self, user_id: str) -> dict | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT id, email, display_name, created_at FROM users WHERE id=?", (user_id,)).fetchone()
        return {"id": row[0], "email": row[1], "displayName": row[2], "createdAt": row[3]} if row else None

    def claim_legacy_state(self, user_id: str) -> bool:
        """Give the pre-login single-user DB document to the first account ever created."""
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS execution_state (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS user_execution_state (user_id TEXT PRIMARY KEY, document TEXT NOT NULL)")
            if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 1:
                return False
            row = db.execute("SELECT document FROM execution_state WHERE id=1").fetchone()
            if not row:
                return False
            document = re.sub(r'"userId":\s*"local"', json.dumps({"userId": user_id})[1:-1], row[0])
            db.execute("INSERT OR IGNORE INTO user_execution_state VALUES (?, ?)", (user_id, document))
            return True

    # sessions --------------------------------------------------------------
    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (_token_hash(token), user_id, _now() + SESSION_DAYS * 86400))
        return token

    def session_user(self, token: str | None) -> str | None:
        if not token:
            return None
        with closing(self.connect()) as db:
            row = db.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash=?",
                             (_token_hash(token),)).fetchone()
        if not row or row[1] < _now():
            return None
        return row[0]

    def delete_session(self, token: str | None):
        if not token:
            return
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))

    # workspace (projects, milestones, events, memories) --------------------
    def read_workspace(self, user_id: str) -> dict | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT document, updated_at FROM user_workspace WHERE user_id=?", (user_id,)).fetchone()
        return {**json.loads(row[0]), "updatedAt": row[1]} if row else None

    def write_workspace(self, user_id: str, document: dict) -> str:
        updated = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO user_workspace VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE "
                       "SET document=excluded.document, updated_at=excluded.updated_at",
                       (user_id, json.dumps(document, ensure_ascii=False), updated))
        return updated


class UserScopedStore:
    """Looks like one ExecutionStore, but reads and writes the logged-in user's document.

    Routers keep a single store object; each request resolves to the user that the
    auth middleware put into ``current_user_id``.
    """

    def __init__(self, path=None):
        self.path = ExecutionStore(path).path

    def _store(self) -> ExecutionStore:
        user_id = current_user_id.get()
        if not user_id:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        return ExecutionStore(self.path, user_id=user_id)

    @property
    def user_id(self):
        return self._store().user_id

    def read(self):
        return self._store().read()

    def change(self, revision, mutation):
        return self._store().change(revision, mutation)


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    displayName: str = Field(min_length=1, max_length=40)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class WorkspaceDocument(BaseModel):
    projects: list[dict] = Field(default_factory=list, max_length=500)
    milestones: list[dict] = Field(default_factory=list, max_length=5000)
    events: list[dict] = Field(default_factory=list, max_length=5000)
    memories: list[dict] = Field(default_factory=list, max_length=2000)


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="올바른 이메일 주소를 입력해 주세요.")
    return email


def auth_router(auth: AuthStore, *, secure_cookies: bool = False) -> APIRouter:
    router = APIRouter(prefix="/api/auth")
    failures: dict[str, list[int]] = {}

    def throttle(key: str):
        recent = [t for t in failures.get(key, []) if t > _now() - FAILURE_WINDOW]
        failures[key] = recent
        if len(recent) >= MAX_FAILURES:
            raise HTTPException(status_code=429, detail="로그인 시도가 너무 많습니다. 15분 후 다시 시도해 주세요.")

    def start_session(response: Response, user: dict) -> dict:
        token = auth.create_session(user["id"])
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                            samesite="lax", secure=secure_cookies, path="/")
        return {"user": user}

    @router.post("/signup")
    def signup(request: SignupRequest, response: Response):
        email = _normalize_email(request.email)
        if request.password.strip() != request.password or len(set(request.password)) < 4:
            raise HTTPException(status_code=422, detail="비밀번호는 앞뒤 공백 없이 8자 이상, 서로 다른 문자 4개 이상이어야 합니다.")
        try:
            user = auth.create_user(email, request.password, request.displayName.strip())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        user["claimedLegacyData"] = auth.claim_legacy_state(user["id"])
        return start_session(response, user)

    @router.post("/login")
    def login(request: LoginRequest, response: Response, http: Request):
        email = request.email.strip().lower()
        key = f"{email}|{http.client.host if http.client else ''}"
        throttle(key)
        user = auth.authenticate(email, request.password)
        if not user:
            failures.setdefault(key, []).append(_now())
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
        failures.pop(key, None)
        return start_session(response, user)

    @router.post("/logout")
    def logout(http: Request, response: Response):
        auth.delete_session(http.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    def me(http: Request):
        user_id = auth.session_user(http.cookies.get(SESSION_COOKIE))
        user = auth.get_user(user_id) if user_id else None
        if not user:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        return {"user": user}

    return router


def workspace_router(auth: AuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/workspace")

    def user_id() -> str:
        value = current_user_id.get()
        if not value:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        return value

    @router.get("")
    def read():
        doc = auth.read_workspace(user_id())
        if doc is None:
            return {"exists": False, "projects": [], "milestones": [], "events": [], "memories": [], "updatedAt": None}
        return {"exists": True, **doc}

    @router.put("")
    def write(document: WorkspaceDocument):
        updated = auth.write_workspace(user_id(), document.model_dump())
        return {"exists": True, "updatedAt": updated}

    return router
