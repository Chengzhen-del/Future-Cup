"""巡检上报：图片 + 语音文本 + 传感器 -> Agent -> 定级结论并落库。

端侧用 multipart 提交（主链路）：
  image   = 图片文件（img 归 store.finalize_inspection 落盘 + 登记 media）
  audio   = 音频文件（初赛只留证、不转写，可省略）
  payload = JSON 字符串（对应 InspectReq）
"""
import json

from fastapi import (APIRouter, Depends, File, Form, Header, HTTPException, Request,
                     UploadFile)
from fastapi.responses import FileResponse

from app.agent.state_machine import run_once
from app.config import settings
from app.schemas import InspectReq, InspectResp
from app.security import require_role
from app.services import store
from app.services.pdf_report import render_inspection_pdf

router = APIRouter(tags=["inspections"])

MAX_IMAGE_MB = 10


def _base(request: Request) -> str:
    """P1-10：图片绝对地址基址（优先 PUBLIC_BASE_URL）。"""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


def _token(request: Request) -> str:
    """v8：取当前请求的 Bearer token，用于给图片地址附加 ?token=（/media 已鉴权）。"""
    parts = request.headers.get("authorization", "").split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return request.query_params.get("token", "")


def _fill_abs(resp: InspectResp, request: Request) -> InspectResp:
    """v8：始终按当前请求重算绝对地址，确保带上 token（含缩略图）。"""
    base, token = _base(request), _token(request)
    resp.imageAbsoluteUrl = store.absolute_media_url(resp.imageUrl, base, token)
    resp.imageThumbAbsoluteUrl = store.absolute_media_url(resp.imageThumbUrl, base, token)
    return resp


@router.post("/inspections/upload", response_model=InspectResp,
             summary="上传巡检数据（推荐，multipart 带图）")
async def upload(request: Request,
                 image: UploadFile | None = File(None),
                 audio: UploadFile | None = File(None),
                 payload: str = Form("{}"),
                 requestId: str = Form(""),
                 idempotency_key: str = Header("", alias="Idempotency-Key")):
    try:
        req = InspectReq(**json.loads(payload or "{}"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"payload 解析失败: {e}")

    # 🟢 P0-4: 幂等键——同一次提交重传（弱网重试）直接返回已有结果，不重复落库
    rid = (requestId or idempotency_key or "").strip()
    if rid:
        existed = store.get_inspection_by_request_id(rid)
        if existed:
            resp = store.inspection_to_resp(existed, _base(request), _token(request))
            resp.duplicate = True
            return resp

    image_bytes = b""
    if image is not None:
        image_bytes = await image.read()
        if len(image_bytes) > MAX_IMAGE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail="图片超过 10MB")
    # audio：初赛「录音留证不转写」，此处接收不处理（媒体归档后续补）
    resp = await run_once(req, image_bytes, rid)
    return _fill_abs(resp, request)


@router.post("/inspections", response_model=InspectResp, summary="纯 JSON 上报（无图）")
async def create(req: InspectReq, request: Request):
    return _fill_abs(await run_once(req, b""), request)


@router.get("/inspections", summary="巡检记录列表（同步摘要 DTO，可选分页/筛选）")
def list_inspections(request: Request, limit: int = 50, page: int | None = None,
                     pageSize: int = 20, level: str = "", deviceId: str = "",
                     startTime: str = "", endTime: str = ""):
    items = store.list_inspections(limit=limit, level=level, device_id=deviceId,
                                   start_time=startTime, end_time=endTime,
                                   base_url=_base(request), token=_token(request))
    return store.paginate(items, page, pageSize)


@router.get("/inspections/{inspection_id}", response_model=InspectResp,
            summary="巡检详情（与 WS final 同一 DTO，含 findings / steps）")
def get_inspection(inspection_id: str, request: Request):
    d = store.get_inspection(inspection_id)
    if not d:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    return store.inspection_to_resp(d, _base(request), _token(request))


@router.delete("/inspections/{inspection_id}",
               summary="删除巡检（admin，硬删并下发同步墓碑）")
def delete_inspection(inspection_id: str, _user=Depends(require_role("admin"))):
    d = store.delete_inspection(inspection_id)
    if not d:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    return {"ok": True, **d}


@router.get("/inspections/{inspection_id}/report.pdf",
            summary="导出巡检报告 PDF（含原图与判读结论）")
def export_pdf(inspection_id: str):
    d = store.get_inspection(inspection_id)
    if not d:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    try:
        path = render_inspection_pdf(d)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PDF 生成失败: {e}")
    return FileResponse(path, media_type="application/pdf",
                        filename=f"{inspection_id}.pdf")
