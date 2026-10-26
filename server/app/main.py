import base64
import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .adaptive.api import adaptive_router
from .auth import SESSION_COOKIE, AuthStore, UserScopedStore, auth_router, current_user_id, workspace_router
from .execution_api import execution_router
from .execution_store import ConflictError, ExecutionStore
from .planner_chat import planner_chat_router
from .execution_llm import ExecutionLLM
from .planner import PlanGenerationError


PUBLIC_API_PATHS = {"/api/health", "/api/auth/signup", "/api/auth/login", "/api/auth/logout", "/api/auth/me"}


def _auth_enabled(explicit, execution_store):
    if explicit is not None:
        return explicit
    env = os.getenv("REPLAN_AUTH", "").strip().lower()
    if env in {"0", "false", "off", "no"}:
        return False
    # Tests that inject their own single-user store keep the old open behaviour.
    return execution_store is None


def create_app(execution_store=None, execution_llm=None, *, auth: bool | None = None, db_path=None) -> FastAPI:
    app = FastAPI(title="PlannerKK API")
    auth_enabled = _auth_enabled(auth, execution_store)
    auth_store = AuthStore(db_path or (execution_store.path if execution_store is not None else None))
    if auth_enabled:
        store = UserScopedStore(auth_store.path)
    else:
        store = execution_store or ExecutionStore(db_path)
    app.state.auth_enabled = auth_enabled
    app.state.auth_store = auth_store
    app.include_router(auth_router(auth_store, secure_cookies=os.getenv("REPLAN_SECURE_COOKIES", "") == "1"))
    if auth_enabled:
        app.include_router(workspace_router(auth_store))
    app.include_router(execution_router(store, execution_llm))
    app.include_router(adaptive_router(store, execution_llm))
    app.include_router(planner_chat_router(store, execution_llm or ExecutionLLM()))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        fields = {"goal": "요청 내용 또는 프로젝트 목표", "startDate": "시작일", "dueDate": "마감일", "estimatedHours": "예상 시간", "title": "제목"}
        labels = sorted({fields.get(str(e["loc"][-1]), "입력 항목") for e in exc.errors()})
        return JSONResponse(status_code=422, content={"detail": "입력값을 확인해 주세요: " + ", ".join(labels) + ". 요청은 3자 이상이며 날짜와 예상 시간을 확인해 주세요."})

    @app.exception_handler(ConflictError)
    async def conflict_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(PlanGenerationError)
    async def generation_error(request, exc):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    @app.get("/api/auth/config")
    async def auth_config():
        return {"enabled": auth_enabled}

    PUBLIC_API_PATHS.add("/api/auth/config")

    @app.middleware("http")
    async def require_login(request, call_next):
        path = request.url.path
        if not auth_enabled or not path.startswith("/api/") or path in PUBLIC_API_PATHS:
            return await call_next(request)
        user_id = auth_store.session_user(request.cookies.get(SESSION_COOKIE))
        if not user_id:
            return JSONResponse(status_code=401, content={"detail": "로그인이 필요합니다."})
        token = current_user_id.set(user_id)
        try:
            return await call_next(request)
        finally:
            current_user_id.reset(token)

    demo_password = os.getenv("DEMO_PASSWORD", "")

    @app.middleware("http")
    async def demo_login(request, call_next):
        if not demo_password or request.url.path == "/api/health":
            return await call_next(request)
        try:
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            _, _, given = base64.b64decode(token).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            scheme, given = "", ""
        if scheme.lower() == "basic" and secrets.compare_digest(given.encode(), demo_password.encode()):
            return await call_next(request)
        return Response("Re:plan 시연용 비밀번호가 필요합니다.", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="replan-demo", charset="UTF-8"'},
                        media_type="text/plain; charset=utf-8")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            os.getenv(
                "FRONTEND_ORIGIN",
                "http://localhost:5173",
            )
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    # Optional single-server local preview after `npm run build`.
    dist = Path(__file__).resolve().parents[2] / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
