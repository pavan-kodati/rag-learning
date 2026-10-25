"""Request dependencies: database connection, runtime deps, audit helper."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from fastapi import Request

from legal_workspace.db.pool import Conn

from ..db import audit as audit_repo
from ..db.pool import connection
from ..deps import Deps
from .security import User


def get_conn() -> Iterator[Conn]:
    """One pooled connection per request: commit on success, roll back on any error."""
    with connection() as conn:
        yield conn


def get_deps(request: Request) -> Deps:
    return request.app.state.deps


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def audit(conn: Conn, request: Request, user: User, action: str, *, matter_id: UUID | str | None = None, entity: str | None = None,
          entity_id: Any = None, detail: dict[str, Any] | None = None) -> None:  # fmt: skip
    audit_repo.record(
        conn, actor=user.username, role=user.role, action=action, matter_id=str(matter_id) if matter_id else None, entity=entity,
        entity_id=str(entity_id) if entity_id else None, detail=detail, request_id=getattr(request.state, "request_id", None),
    )  # fmt: skip
