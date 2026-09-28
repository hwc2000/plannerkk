import os
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .execution_api import execution_router
from .execution_store import ConflictError

from .planner import (
    PlanDraft,
    PlanDraftRequest,
    PlanGenerationError,
    parse_plan_for_project,
)
from .project_overview import router as project_overview_router


class PlanGenerator(Protocol):
    async def generate(self, request: PlanDraftRequest) -> object: ...


def create_app(generator: PlanGenerator | None = None, execution_store=None, execution_llm=None) -> FastAPI:
    app = FastAPI(title="PlannerKK API")
    app.include_router(execution_router(execution_store, execution_llm))

    @app.exception_handler(ConflictError)
    async def conflict_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(PlanGenerationError)
    async def generation_error(request, exc):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})
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

    app.include_router(project_overview_router)

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok"
        }

    @app.post(
        "/api/ai/plan-draft",
        response_model=PlanDraft,
    )
    async def create_plan_draft(
        request: PlanDraftRequest
    ):
        active_generator = generator
        owns_generator = active_generator is None

        if active_generator is None:
            from .openai_planner import (
                OpenAIPlanGenerator,
            )

            try:
                active_generator = (
                    OpenAIPlanGenerator.from_env()
                )
            except PlanGenerationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=str(exc),
                ) from exc

        try:
            payload = await active_generator.generate(
                request
            )

            return parse_plan_for_project(
                payload,
                project_start=(
                    request.project.startDate
                ),
                project_due=(
                    request.project.dueDate
                ),
            )

        except PlanGenerationError as exc:
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "AI 계획 생성에 실패했습니다."
                ),
            ) from exc

        finally:
            if owns_generator:
                try:
                    await getattr(
                        active_generator,
                        "close",
                    )()
                except Exception:
                    pass

    # Optional single-server local preview after `npm run build`.
    dist = Path(__file__).resolve().parents[2] / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
