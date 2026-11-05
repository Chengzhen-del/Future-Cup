"""端侧同步：启动全量快照 / 增量拉取 / 冲突仲裁（P1-6、P1-7）。"""
from fastapi import APIRouter, Request

from app.config import settings
from app.schemas import ConflictReq, ConflictResp, SyncSnapshot
from app.services import store

router = APIRouter(tags=["sync"])


def media_base(request: Request) -> str:
    """图片绝对地址的基址：优先配置项，其次请求来源。"""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


def request_token(request: Request) -> str:
    """v8：当前 Bearer token（给图片地址附加 ?token=，/media 已鉴权）。"""
    parts = request.headers.get("authorization", "").split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return request.query_params.get("token", "")


@router.get("/sync/snapshot", response_model=SyncSnapshot,
            summary="启动全量 / 增量同步快照（since 基于 updatedAt）")
def sync_snapshot(request: Request, deviceId: str = "", since: str = ""):
    """不带 since 拉全量；之后把上一次返回的 serverTime 作为 since 拉增量。

    - inspections 固定为 SyncInspection 摘要（不含 findings / steps，详情走 /inspections/{id}）
    - deleted 为删除墓碑 [{tableName,recordId,deviceId,deletedAt}]，端侧据此本地删除
    """
    return store.get_sync_snapshot(device_id=deviceId, since=since,
                                   base_url=media_base(request),
                                   token=request_token(request))


@router.post("/sync/conflict", response_model=ConflictResp, summary="冲突仲裁（白名单 + 版本比对）")
def sync_conflict(req: ConflictReq):
    """cloud_version 与服务端当前 updatedAt 一致 → 接受端侧改动；否则云端优先。"""
    return store.resolve_conflict(req.table, req.id, req.cloudVersion, req.deviceChanges)
