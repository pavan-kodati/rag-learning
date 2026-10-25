from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...config import get_settings
from ...errors import Unauthorized
from ..deps import client_ip
from ..security import User, authenticate, current_user, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@router.get("/config")
def config() -> dict[str, bool]:
    return {"enabled": get_settings().auth_enabled}


@router.post("/login")
def login(body: LoginRequest, request: Request) -> dict[str, object]:
    s = get_settings()
    request.app.state.login_limiter.check(f"{client_ip(request)}:{body.username.lower()}")
    user = authenticate(body.username, body.password, s)
    if user is None:
        raise Unauthorized("invalid credentials")
    token, ttl = issue_token(user, s)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ttl,
        "username": user.username,
        "role": user.role,
    }


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, str]:  # noqa: B008
    return {"username": user.username, "role": user.role}
