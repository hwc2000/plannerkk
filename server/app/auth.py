"""Who is calling, and that user's own store for the rest of the request.

Every API reaches the database through ``CurrentUserStore``, which resolves to
the store of the user ``current_user`` names.  One user's document is never
handed to another, so users stay independent the same way projects do.

Until login exists every request is the local user.  The login work replaces
the body of ``current_user`` only (for example: read the session cookie, return
its user id, raise 401 without one); nothing else needs to change.
"""
from contextvars import ContextVar

from fastapi import Depends, Request

from .execution_store import ExecutionStore

LOCAL_USER = "local"

_request_store: ContextVar[ExecutionStore | None] = ContextVar("request_store", default=None)


def current_user(request: Request) -> str:
    """The calling user's id. Placeholder until login: everyone is the local user."""
    return LOCAL_USER


class UserStores:
    """Hands out each user's own store; all of them live in the same database file."""

    def __init__(self, base: ExecutionStore):
        self.base = base

    def for_user(self, user_id: str) -> ExecutionStore:
        if user_id == self.base.user_id:
            return self.base
        return ExecutionStore(self.base.path, user_id=user_id)

    async def bind(self, user_id: str = Depends(current_user)) -> None:
        """Request dependency: from here on, this request uses only this user's store.

        Async on purpose: a value set here reaches sync endpoints, which run on a
        copy of this context; one set inside a worker thread would not come back.
        """
        _request_store.set(self.for_user(user_id))


class CurrentUserStore:
    """Stands in for the calling user's store; routers hold this instead of one fixed store."""

    def _store(self) -> ExecutionStore:
        store = _request_store.get()
        if store is None:
            # Fail closed: without a known user there is no store to use.
            raise RuntimeError("요청한 사용자를 알 수 없어 저장소를 열 수 없습니다.")
        return store

    @property
    def user_id(self) -> str:
        return self._store().user_id

    def read(self):
        return self._store().read()

    def change(self, revision, mutation):
        return self._store().change(revision, mutation)
