"""可观测与运维接口：Trace 回放 / 告警处理 / Token 成本 / 媒体策略（P2-13、P2-14、P2-15、P1-12）。"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.schemas import AlertItem, AlertResolveReq, MediaPolicy, TraceDetail
from app.services import store

router = APIRouter(tags=["ops"])


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- Trace ----------------
@router.get("/traces", summary="Trace 列表（分页/筛选，不含 events）")
def list_traces(deviceId: str = "", level: str = "", startTime: str = "",
                endTime: str = "", page: int | None = None, pageSize: int = 20,
                limit: int = 50):
    items = store.list_traces(device_id=deviceId or None, limit=limit, level=level,
                              start_time=startTime, end_time=endTime)
    data = store.paginate(items, page, pageSize)
    if isinstance(data, list):
        return {"traces": data, "total": len(data), "page": 1, "pageSize": len(data)}
    return {"traces": data["items"], "total": data["total"],
            "page": data["page"], "pageSize": data["pageSize"]}


@router.get("/traces/{trace_id}", response_model=TraceDetail,
            summary="Trace 详情（events 已标准化，按 seq 可直接回放）")
def get_trace(trace_id: int):
    t = store.get_trace(trace_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trace 不存在")
    return t


# ---------------- 告警 ----------------
@router.get("/alerts", summary="告警列表（分页/筛选，含处理人）")
def list_alerts(unresolved: bool = True, limit: int = 50, level: str = "",
                category: str = "", startTime: str = "", endTime: str = "",
                page: int | None = None, pageSize: int = 20):
    items = store.list_alerts(unresolved_only=unresolved, limit=limit, level=level,
                              category=category, start_time=startTime, end_time=endTime)
    for a in items:
        a["resolved"] = bool(a.get("resolved"))
    data = store.paginate(items, page, pageSize)
    if isinstance(data, list):
        return {"alerts": data, "total": len(data), "page": 1, "pageSize": len(data)}
    return {"alerts": data["items"], "total": data["total"],
            "page": data["page"], "pageSize": data["pageSize"]}


@router.post("/alerts/{alert_id}/resolve", summary="处理告警（记录处理人/时间/备注）")
def resolve_alert(alert_id: int, request: Request, body: AlertResolveReq | None = None):
    user = getattr(request.state, "user", None) or {}
    d = store.resolve_alert(alert_id, note=(body.note if body else ""),
                            user_id=user.get("userId", ""))
    if not d:
        raise HTTPException(status_code=404, detail="告警不存在")
    return {"ok": True, "alert": AlertItem(**d).model_dump()}


# ---------------- Token 成本 ----------------
@router.get("/stats/tokens", summary="Token 用量/成本（按天/调用方/模型/用户/设备/会话）")
def token_stats(days: int = 7):
    return store.get_token_stats(days=days)


# ---------------- 媒体策略 ----------------
@router.get("/system/media-policy", response_model=MediaPolicy,
            summary="媒体文件生命周期与图片 URL 规则")
def media_policy():
    return MediaPolicy(
        retentionDays=settings.MEDIA_RETENTION_DAYS,
        keepFailedUploads=settings.KEEP_FAILED_UPLOADS,
        note=(f"原图/录音保留 {settings.MEDIA_RETENTION_DAYS} 天（随归档清理）；"
              "巡检记录删除时同步删除 media 登记；暂不支持缩略图与 PDF 导出。"),
    )
