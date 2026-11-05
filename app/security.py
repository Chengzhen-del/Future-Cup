"""角色权限（RBAC）：路由级依赖，失败走统一 403。

角色约定：
- inspector：巡检员，可查任务/设备/工单/巡检、改自己的任务状态、上报巡检、处理告警
- reviewer ：复核员，可查看全部数据、处理工单与告警（预留，当前未建账号）
- admin    ：管理员，额外可执行归档/清理等运维操作
"""
from fastapi import HTTPException, Request

from app.config import settings


def require_role(*roles: str):
    def _dep(request: Request):
        user = getattr(request.state, "user", None)
        if not user:
            if not settings.AUTH_ENABLED:
                return {"userId": "", "name": "", "role": "admin", "team": ""}
            raise HTTPException(status_code=401,
                                detail={"code": "UNAUTHORIZED",
                                        "message": "未登录或 token 已失效"})
        if roles and user.get("role") not in roles:
            raise HTTPException(status_code=403,
                                detail={"code": "FORBIDDEN",
                                        "message": f"该操作需要 {'/'.join(roles)} 角色，"
                                                   f"当前角色为 {user.get('role')}"})
        return user
    return _dep
