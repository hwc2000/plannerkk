import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .execution_api import BusyEvent, Mutation
from .execution_store import ConflictError
from .plan_merge import thread_key
from .planner_actions import action_valid, public_state, scoped_action
from .planner_skills import ChatContext, basic_info, run_turn

KST = timezone(timedelta(hours=9))
HISTORY_LIMIT = 100
CONTEXT_MESSAGES = 16


class ChatProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(max_length=200)
    goal: str = Field(default="", max_length=2000)
    startDate: date
    dueDate: date


class ChatMessage(Mutation):
    text: str = Field(min_length=1, max_length=2000)
    consent: bool = False
    project: ChatProject | None = None
    # Calendar events stay in the browser; the week lookup subtracts them.
    events: list[BusyEvent] = Field(default_factory=list, max_length=500)


class ThreadReset(Mutation):
    projectId: str | None = Field(default=None, max_length=200)


def planner_chat_router(store, llm):
    router = APIRouter(prefix="/api/execution/chat")

    def envelope(state):
        public = public_state(state)
        return {**public, "llmAvailable": bool(os.getenv("OPENAI_API_KEY", "").strip()),
                "model": os.getenv("OPENAI_PLAN_MODEL", "gpt-4o-mini")}

    @router.post("/message")
    async def message(request: ChatMessage):
        if not request.consent:
            raise HTTPException(400, "대화·프로필·가용 시간·현재 계획을 AI에 전송하는 데 동의해 주세요.")
        state = store.read()
        if state["revision"] != request.revision:
            raise ConflictError("화면을 새로 불러온 뒤 다시 보내 주세요.")
        if not state.get("profile"):
            raise ValueError("먼저 설문으로 프로필을 만들고 확정해 주세요.")
        if request.project and (state.get("closedProjects") or {}).get(request.project.id):
            raise ValueError("끝낸 프로젝트예요. 다시 열면 이어서 대화할 수 있어요.")
        key = thread_key(request.project.id if request.project else None)
        thread = state.get("plannerThreads", {}).get(key) or {"messages": [], "action": None}
        now = datetime.now(KST).replace(tzinfo=None, second=0, microsecond=0)
        project_id = request.project.id if request.project else None
        waiting = thread.get("action") if action_valid(state, thread.get("action"), project_id) else None
        # This conversation sees the user profile and this project's own values, never another project's.
        ctx = ChatContext(state=state, user_id=store.user_id, today=now.date(), now=now, events=request.events,
                          project=request.project.model_dump(mode="json") if request.project else None,
                          waiting=waiting)
        # The model reads its own earlier words only, not the notes code put under them,
        # so it does not learn to repeat them.
        history = [{"role": m["role"], "content": m.get("reply", m["content"])}
                   for m in thread["messages"][-CONTEXT_MESSAGES:]]
        turn = await run_turn(llm, ctx, basic_info(ctx, history, request.text))

        def save(doc):
            threads = doc.setdefault("plannerThreads", {})
            current = threads.get(key) or {"messages": [], "action": None}
            messages = [*current["messages"],
                        {"id": str(uuid4()), "role": "user", "content": request.text},
                        # Which skill answered and what it read, so the routing stays visible.
                        {"id": str(uuid4()), "role": "assistant", "content": turn.content, "reply": turn.reply,
                         "skill": turn.skill, "lookups": turn.lookups}]
            # A repeated/acknowledged card keeps its ORIGINAL basis. Only a genuinely
            # new proposal is stamped; chatting cannot make an unsafe old card fresh.
            action = None
            if turn.action:
                action = waiting if waiting and turn.action == waiting else scoped_action(
                    doc, {**turn.action, "revision": request.revision + 1}, project_id)
            threads[key] = {"messages": messages[-HISTORY_LIMIT:],
                            "action": action,
                            "updatedAt": now.isoformat(timespec="seconds")}
        return envelope(store.change(request.revision, save))

    @router.post("/reset")
    def reset(request: ThreadReset):
        return envelope(store.change(request.revision,
                                     lambda doc: doc.setdefault("plannerThreads", {}).pop(thread_key(request.projectId), None)))

    return router
