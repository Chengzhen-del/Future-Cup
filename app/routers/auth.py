"""登录鉴权（P0-3）：账号密码 → access / refresh token。

token 落库（auth_tokens），服务重启后仍有效；吊销用 revoked 标记。
默认账号见 store._seed_users：admin/admin123、inspector/inspector123。
"""
from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.schemas import LoginReq, TokenPair, UserInfo
from app.services import store

router = APIRouter(prefix="/auth", tags=["auth"])


def _bearer(authorization: str) -> str:
    parts = (authorization or "").split()
    return parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else ""


@router.post("/login", response_model=TokenPair, summary="账号密码登录")
def login(body: LoginReq):
    u = store.get_user_by_name(body.username)
    if not u or not store.verify_password(body.password, u.get("passwordHash") or ""):
        raise HTTPException(status_code=401,
                            detail={"code": "INVALID_CREDENTIALS",
                                    "message": "用户名或密码错误"})
    access = store.issue_token(u["id"], "access", settings.ACCESS_TOKEN_TTL_MIN)
    refresh = store.issue_token(u["id"], "refresh", settings.REFRESH_TOKEN_TTL_DAYS * 1440)
    store.touch_login(u["id"])
    return TokenPair(
        accessToken=access, refreshToken=refresh,
        expiresIn=settings.ACCESS_TOKEN_TTL_MIN * 60,
        user=UserInfo(userId=u["id"], name=u["name"],
                      role=u["role"], team=u["team"] or ""))


@router.post("/refresh", response_model=TokenPair, summary="刷新 access token")
def refresh(body: dict):
    rt = (body or {}).get("refreshToken", "")
    info = store.verify_token(rt, kind="refresh")
    if not info:
        raise HTTPException(status_code=401,
                            detail={"code": "INVALID_REFRESH_TOKEN",
                                    "message": "refreshToken 无效或已过期"})
    u = store.get_user(info["userId"]) or {}
    access = store.issue_token(info["userId"], "access", settings.ACCESS_TOKEN_TTL_MIN)
    return TokenPair(
        accessToken=access, refreshToken=rt,
        expiresIn=settings.ACCESS_TOKEN_TTL_MIN * 60,
        user=UserInfo(userId=info["userId"], name=u.get("name", ""),
                      role=u.get("role", ""), team=u.get("team", "")))


@router.post("/logout", summary="退出（吊销当前 access token）")
def logout(authorization: str = Header("")):
    token = _bearer(authorization)
    if token:
        store.revoke_token(token)
    return {"ok": True}


@router.get("/me", response_model=UserInfo, summary="当前登录用户")
def me(authorization: str = Header("")):
    info = store.verify_token(_bearer(authorization))
    if not info:
        raise HTTPException(status_code=401,
                            detail={"code": "UNAUTHORIZED",
                                    "message": "未登录或 token 已失效"})
    return UserInfo(**info)
